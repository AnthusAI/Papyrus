"""Export a Papyrus relevance run for the Cyclotron marketing site.

The recording follows the editorial-run fixture's schema 2 (Cyclotron
``scripts/export_editorial_run_fixture.py``) with ``source: "papyrus-live"``:
per cycle the item's title and source, the decision shown before the review,
the editor's label and reason code, and the review program's reason and
propensity; per window of 100 decisions the metrics on reviewed decisions,
routing, cyclotron changes, and measured usage and cost at list prices; and
``usage_total`` with the price basis in the attribution.

Consent and redaction: an editor's explanation is exported only when the
review was marked shareable and the export is run with explanations on.
Reviewer names, emails and private text beyond titles and public URLs are
never exported.
"""
from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

# List prices, USD per million tokens. Jev's is TypeSafe's published price; any
# other model's price must be given with its source and the date it was read.
KNOWN_PRICES = {
    "jev": {"input_usd_per_mtok": 0.042, "output_usd_per_mtok": 0.0, "source": "TypeSafe's published price"},
}
WINDOW = 100
DISCLOSURE = ("Live Papyrus newsroom data: the relevance cyclotron's decisions about candidate sources, shown before "
              "each review, and the labels editors gave the decisions the review program sent them. Explanations are "
              "quoted only where the editor agreed. Metrics count reviewed decisions only.")


def price_basis(plan, optimizer_price: Mapping[str, Any] | None) -> dict[str, Any]:
    """The decision model's and optimizer's list prices, each with its source."""
    decision_provider = plan.decision_model["provider"]
    if decision_provider not in KNOWN_PRICES:
        raise ValueError(f"No list price is known for decision model {decision_provider}; give one with its source.")
    decision = {"model": plan.decision_model["model"], **KNOWN_PRICES[decision_provider]}
    if optimizer_price is None:
        optimizer = {"model": (plan.optimizer or {}).get("model"), "input_usd_per_mtok": 0.0, "output_usd_per_mtok": 0.0,
                     "source": "no optimizer price given; optimizer calls must be zero"}
    else:
        missing = {"input_usd_per_mtok", "output_usd_per_mtok", "source"} - set(optimizer_price)
        if missing:
            raise ValueError(f"The optimizer price needs {', '.join(sorted(missing))}.")
        optimizer = {"model": (plan.optimizer or {}).get("model"), **optimizer_price}
    return {"basis": "list prices, USD per million tokens, applied to the provider-reported usage on every recorded call",
            "decision_model": decision, "optimizer": optimizer}


def build_recording(*, plan, publication: str, log: Sequence[Mapping[str, Any]], usage: Mapping[str, Any],
                    events: Sequence[Mapping[str, Any]], shareable: Mapping[str, bool], prices: Mapping[str, Any],
                    include_explanations: bool = True, title: str | None = None) -> dict[str, Any]:
    """Build the fixture from the SDK's decision log, usage and subscribe events. No model call."""
    from decision_flywheel.routing_metrics import Decision, routing

    if usage["total"]["optimizer"]["requests"] and prices["optimizer"]["source"].startswith("no optimizer price"):
        raise ValueError("This run made optimizer calls; give the optimizer's list price and its source.")
    classifier = plan.definition.classifiers[0]
    labels = tuple(classifier.labels)
    negative = next(label for label in labels if label != classifier.positive_label)
    changes = _changes_by_decision(events)
    cycles = []
    for row in log:
        decision = row["decision"]
        result = decision["classifiers"][classifier.id]
        review = row["reviews"].get(classifier.id) or {}
        labeled = review.get("label") is not None
        item = row.get("item") or {}
        cycle = {
            "n": row["n"],
            "predicted": result["label"],
            "confidence": result["confidence"],
            "probabilities": result["probabilities"],
            "calibration": {"version": result["version"], "fingerprint": result["fingerprint"]},
            "article": {"title": item.get("title"), "source_url": item.get("source_uri"), "domain": item.get("domain")},
            "feedback_revealed": labeled,
            "feedback_propensity": decision["review"]["propensity"],
            "review_selected": decision["review"]["selected"],
            "review_reason": decision["review"]["reason"],
            "events": changes.get(decision["decisionId"], []),
        }
        if labeled:
            cycle["actual"] = review["label"]
            cycle["selected_by"] = review.get("selectedBy")
        if review.get("reasonCode"):
            cycle["reason_code"] = review["reasonCode"]
        if review.get("kind") == "no-label":
            cycle["reviewed_without_label"] = True
        if (include_explanations and review.get("explanation") and review.get("reviewId")
                and shareable.get(review["reviewId"]) is True):
            cycle["editor_explanation"] = review["explanation"]
        cycles.append(cycle)
    windows = _windows(cycles, labels, usage, routing, Decision)
    return {
        "schema_version": 2,
        "source": "papyrus-live",
        "title": title or f"{publication}: live relevance reviews",
        "disclosure": DISCLOSURE,
        "rubric_summary": classifier.question,
        "attribution": {"publication": publication, "cyclotron": plan.definition.id,
                        "definition_fingerprint": plan.definition.fingerprint, "price_basis": prices},
        "task_hash": plan.definition.fingerprint,
        "scenarios": {
            "live": {
                "feedback_policy": {"mode": "review-program", "selection_timing": "after decision, before review",
                                    "negative_label": negative,
                                    "summary": "The review program sends low-confidence decisions, a random audit share, "
                                               "and confident decisions at its current rate to editors."},
                "windows": windows,
                "usage_total": usage["total"],
                "cycles": cycles,
            }
        },
    }


def _changes_by_decision(events: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Cyclotron changes, attached to the latest decision made before them."""
    changes: dict[str, list[dict[str, Any]]] = {}
    current = None
    for event in events:
        kind = event.get("kind")
        if kind == "decision":
            current = event["decision"]["decisionId"]
        elif kind in ("promoted", "refit", "dropped") and current:
            changes.setdefault(current, []).append({"type": kind, "version": event.get("version"),
                                                    "summary": event.get("summary"), "labels": event.get("labels")})
        elif kind == "review-rate-changed" and current:
            changes.setdefault(current, []).append({"type": "review-rate", "state": event.get("state"),
                                                    "rate": event.get("rate"), "reason": event.get("reason")})
    return changes


def _metrics(rows: Sequence[tuple[str, Mapping[str, float], str]], labels: Sequence[str]) -> dict[str, Any] | None:
    if not rows:
        return None
    confidences = [probabilities[label] for label, probabilities, _ in rows]
    right = [label == actual for label, _, actual in rows]
    total = len(rows)
    ece = 0.0
    for bucket in range(10):
        members = [i for i, value in enumerate(confidences) if min(9, int(value * 10)) == bucket]
        if members:
            ece += len(members) / total * abs(sum(confidences[i] for i in members) / len(members)
                                              - sum(right[i] for i in members) / len(members))
    per_class = {}
    for name in labels:
        predicted = sum(label == name for label, _, _ in rows)
        actual = sum(value == name for _, _, value in rows)
        hits = sum(label == name == value for label, _, value in rows)
        per_class[name] = {"precision": hits / predicted if predicted else None,
                           "recall": hits / actual if actual else None, "predicted": predicted, "actual": actual}
    return {"count": total, "accuracy": sum(right) / total, "ece": ece, "mean_confidence": sum(confidences) / total,
            "per_class": per_class}


def _windows(cycles, labels, usage, routing, Decision) -> list[dict[str, Any]]:
    usage_windows = {window["window"]: window for window in usage["windows"]}
    windows = []
    for index in range(0, len(cycles), WINDOW):
        chunk = cycles[index:index + WINDOW]
        reviewed = [(cycle["predicted"], cycle["probabilities"], cycle["actual"]) for cycle in chunk
                    if cycle.get("actual") is not None and cycle.get("probabilities")
                    and cycle.get("selected_by") in ("program", "audit")]
        window_usage = usage_windows.get(index // WINDOW + 1, {})
        changes = [event for cycle in chunk for event in cycle["events"]]
        windows.append({
            "window": index // WINDOW + 1,
            "first_cycle": chunk[0]["n"], "last_cycle": chunk[-1]["n"],
            "label_source": "Editor reviews of decisions the review program sent; reviewed decisions only.",
            "decisions": len(chunk),
            "sent_to_review": sum(bool(cycle["review_selected"]) for cycle in chunk),
            "feedback_revealed": sum(bool(cycle["feedback_revealed"]) for cycle in chunk),
            "cyclotron": _metrics(reviewed, labels),
            "routing": {"cyclotron": routing([Decision(label, probabilities[label], actual)
                                              for label, probabilities, actual in reviewed])} if reviewed else None,
            "cyclotron_changes": {"versions": sum(event["type"] == "promoted" for event in changes),
                                  "refits": sum(event["type"] == "refit" for event in changes),
                                  "dropped": sum(event["type"] == "dropped" for event in changes),
                                  "review_rate_changes": sum(event["type"] == "review-rate" for event in changes)},
            "model_calls": {"decision_model": window_usage.get("decision_model", {}).get("requests", 0),
                            "optimizer": window_usage.get("optimizer", {}).get("requests", 0)},
            "wall_clock_seconds": window_usage.get("wall_clock_seconds"),
            "usage": {key: window_usage[key] for key in ("decision_model", "optimizer", "usd") if key in window_usage},
        })
    return windows


def shareable_reviews(client, review_ids: Sequence[str], read_metadata) -> dict[str, bool]:
    """Whether each review's curation Message was marked shareable by its editor."""
    shared = {}
    for review_id in review_ids:
        message = client.get_record("Message", review_id)
        shared[review_id] = bool(message) and read_metadata(client, message).get("shareable") is True
    return shared


def references_export_relevance_recording(flags: list[str]) -> None:
    """papyrus references export-relevance-recording --output <file.json> [--config <steering.yml>]
    [--store <local store dir>] [--no-explanations] [--optimizer-price IN,CACHED,OUT --optimizer-price-source "..."]

    Reads the latest store snapshot from the private bucket (or --store) and
    writes the fixture. Makes no model call and writes nothing to Papyrus.
    """
    import tempfile
    from pathlib import Path

    from decision_flywheel import Cyclotron

    from .graphql_authoring import create_authoring_client
    from .newsroom_doctrine import load_publication_doctrine_seed
    from .options import parse_options
    from .relevance_cyclotron import build_relevance_cyclotron, decision_model_identity
    from .relevance_sweep import SNAPSHOT_NAME, S3SnapshotStore, _HeldLease, _owner_metadata
    from .steering import require_steering_config

    options = parse_options(flags)
    if not isinstance(options.get("output"), str):
        raise ValueError("references export-relevance-recording requires --output <file.json>.")
    steering = require_steering_config(options.get("config"))
    plan = build_relevance_cyclotron(steering, load_publication_doctrine_seed(options.get("doctrine"))["doctrine"])
    optimizer_price = None
    if isinstance(options.get("optimizer-price"), str):
        values = [float(part) for part in options["optimizer-price"].split(",")]
        if len(values) != 3 or not isinstance(options.get("optimizer-price-source"), str):
            raise ValueError("--optimizer-price needs IN,CACHED,OUT USD per million tokens and --optimizer-price-source.")
        optimizer_price = {"input_usd_per_mtok": values[0], "cached_input_usd_per_mtok": values[1],
                           "output_usd_per_mtok": values[2], "source": options["optimizer-price-source"]}
    prices = price_basis(plan, optimizer_price)
    sdk_prices = {name: {key: value for key, value in prices[name].items() if key.endswith("_mtok")}
                  for name in ("decision_model", "optimizer")}
    client, _ = create_authoring_client()
    with tempfile.TemporaryDirectory() as scratch:
        if isinstance(options.get("store"), str):
            store = Path(options["store"])
        else:
            if not plan.s3_prefix:
                raise ValueError("relevanceCyclotron.store.s3Prefix is not set; pass --store.")
            archive, store = Path(scratch) / SNAPSHOT_NAME, Path(scratch) / "store"
            if not S3SnapshotStore().download(f"{plan.s3_prefix.rstrip('/')}/{SNAPSHOT_NAME}", archive):
                raise ValueError("No cyclotron store snapshot exists in the private bucket yet.")
            Cyclotron.restore(archive, store, lease=_HeldLease())
        with Cyclotron.open(store, plan.definition, _NoModel(decision_model_identity(plan)), lease=_HeldLease(),
                            review_program=plan.review_program, seed_rubrics=plan.seed_rubrics) as cyclotron:
            log = cyclotron.decision_log()
            usage = cyclotron.usage(sdk_prices, window=WINDOW)
            events = _all_events(cyclotron)
    review_ids = [review["reviewId"] for row in log for review in row["reviews"].values() if review.get("reviewId")]
    recording = build_recording(plan=plan, publication=steering["publication"]["name"], log=log, usage=usage,
                                events=events, shareable=shareable_reviews(client, review_ids, _owner_metadata),
                                prices=prices, include_explanations=not options.get("no-explanations"))
    Path(options["output"]).write_text(json.dumps(recording, separators=(",", ":"), ensure_ascii=False) + "\n",
                                       encoding="utf-8")
    print(f"references\texport-relevance-recording\t{options['output']}\t{len(log)} decisions\t"
          f"{usage['total']['usd']} USD")


class _NoModel:
    """Opening a store for export makes no model call; any attempt is an error.

    It carries the configured decision model's identity, which the store checks.
    """

    def __init__(self, model_identity: str):
        self.model_identity = model_identity

    async def classify_many(self, *args, **kwargs):
        raise RuntimeError("the recording export never calls a model")


def _all_events(cyclotron) -> list[dict[str, Any]]:
    events, cursor = [], 0
    while True:
        page = cyclotron.subscribe(after=cursor, limit=1000)
        events.extend(page["events"])
        if len(page["events"]) < 1000:
            return events
        cursor = page["cursor"]
