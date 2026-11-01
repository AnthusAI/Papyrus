"""The two learning classifiers of the site Cyclotron: ``reference-link-fit`` and ``idea-pack-fit``.

See docs/idea-context-packs.md sections 3.3 and 4.5, and the Cyclotron learning loop standard (PPY-c6aced: votes train the site's Cyclotron).

* ``reference-link-fit`` answers whether a suggested link between two References deserves to be shown as likely. Its labels are the suggestions
  a person accepted or rejected. The statistical rule it must beat is the Wilson cut of ``suggestion_calibration``.
* ``idea-pack-fit`` answers whether a context pack deserves an idea. Its labels are what a person did with the idea made from the pack (moved it
  forward or spiked it, or accepted or rejected it with ``generated.decision``), joined by ``generated.evidence.packId``. The statistical rule it
  must beat is the pack builders' surprise ordering.

Examples come from decisions people made, never from automation. Each example is a row in the priming import shape (``priming_export``), with the
decision's reason code and note carried as the label's explanation, so the central retraining round can use the editors' words. Nothing here
calls a model: the trained version's predictions arrive as probabilities, and ``evaluate_*`` compares them with the statistical rule on decisions
held out of training. The result is recorded as a promotion flag that stays off until the trained version wins; consumers switch only on it.
"""
from __future__ import annotations

import json
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .auto_accept import DEFAULT_PRECISION
from .monitoring_router import human_actor
from .priming_export import compose_text, iso_day, machine_story_actor, row, scrubbed
from .suggestion_calibration import FEED_INDEX, REFERENCE_KIND, calibrate_kind, decided_suggestions

LINK_CLASSIFIER_ID = "reference-link-fit"
LINK_LABELS = ("fits", "does-not-fit")
LINK_POSITIVE_LABEL = "fits"
LINK_QUESTION = "Is this suggested link between two References one an editor would accept?"
PACK_CLASSIFIER_ID = "idea-pack-fit"
PACK_LABELS = ("worth-an-idea", "not-worth-an-idea")
PACK_POSITIVE_LABEL = "worth-an-idea"
PACK_QUESTION = "Does this context pack deserve an idea from the newsroom?"
LEARNING_CLASSIFIER_IDS = (LINK_CLASSIFIER_ID, PACK_CLASSIFIER_ID)
LINK_SOURCE = "reference-link-decision"
PACK_SOURCE = "idea-pack-decision"
DEFAULT_HELD_OUT_SHARE = 0.3
SIGNIFICANCE = 0.05
PROMOTION_FILE_NAME = "learning-promotion.json"
EDITOR = "editor"


def learning_seed_rubrics() -> dict[str, str]:
    return {
        LINK_CLASSIFIER_ID: ("An editor accepts a suggested link when the two References are about the same thing, share concepts or a source, "
                             "and were published close together. Features: similarity, shared concepts, shared host, publication-date gap, "
                             "whether both References were accepted by people."),
        PACK_CLASSIFIER_ID: ("An editor moves a pack's idea forward when the signal is surprising, the pack is rich in evidence people confirmed, "
                             "and the anchor has not just had an idea. Features: signal type, surprise, pack size, share of human-confirmed "
                             "edges, Message count, days since the last idea on the anchor."),
    }


@dataclass(frozen=True)
class LearningExample:
    example_id: str
    occurred_at: str
    positive: bool
    explanation: str
    features: Mapping[str, Any]
    title: str
    url: str
    summary: str
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def as_row(self, classifier_id: str, positive_label: str, negative_label: str) -> dict[str, Any]:
        summary = self.summary + "\nFeatures: " + json.dumps(self.features, sort_keys=True)
        found = row(self.example_id, self.occurred_at, {"title": self.title, "url": self.url, "summary": summary, "body": ""},
                    {classifier_id: {"label": positive_label if self.positive else negative_label, "explanation": self.explanation}},
                    {**self.provenance, "labeledBy": EDITOR, "modelMade": False, "features": dict(self.features)})
        found["values"]["text"] = compose_text(self.title, self.url, summary, "")
        return found


def explanation_of(reason_code: Any, note: Any) -> str:
    code, text = scrubbed(reason_code), scrubbed(note)
    return f"{code}: {text}" if code and text else code or text


def _metadata(record: Mapping[str, Any]) -> dict[str, Any]:
    raw = record.get("metadata")
    if isinstance(raw, str):
        return json.loads(raw or "{}")
    return dict(raw or {})


def _moment(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _day(value: Any) -> date | None:
    moment = _moment(value)
    return moment.date() if moment else None


def host_of(url: Any) -> str:
    host = (urlparse(str(url or "")).hostname or "").lower()
    return host.removeprefix("www.")


# --- reference-link-fit -------------------------------------------------------------------------------------------------------


def link_features(similarity: float, subject: Mapping[str, Any], target: Mapping[str, Any],
                  subject_concepts: Iterable[str], target_concepts: Iterable[str]) -> dict[str, Any]:
    """The features of one suggestion: similarity, shared concepts, shared host, publication-date gap in days, both References accepted by people."""
    subject_host, target_host = host_of(subject.get("sourceUri")), host_of(target.get("sourceUri"))
    first, second = _day(subject.get("sourcePublishedAt")), _day(target.get("sourcePublishedAt"))
    both_accepted = all(reference.get("curationStatus") == "accepted" and human_actor(str(reference.get("curationStatusUpdatedBy") or ""))
                        for reference in (subject, target))
    return {
        "similarity": similarity,
        "sharedConcepts": len(set(subject_concepts) & set(target_concepts)),
        "sharedHost": bool(subject_host) and subject_host == target_host,
        "publicationGapDays": abs((first - second).days) if first and second else None,
        "bothHumanAccepted": both_accepted,
    }


def link_examples(relations: Sequence[Mapping[str, Any]], references: Mapping[str, Mapping[str, Any]],
                  concepts_by_reference: Mapping[str, Iterable[str]]) -> list[LearningExample]:
    """One example per suggested Reference link a person decided. Rows decided by automation, without a score or of another kind are skipped."""
    examples = []
    for relation in relations:
        metadata = _metadata(relation)
        if (relation.get("objectKind") != "reference" or metadata.get("provenance") != "suggested" or relation.get("score") is None
                or metadata.get("decision") not in ("accepted", "rejected") or not human_actor(str(metadata.get("decidedBy") or ""))):
            continue
        subject_id, target_id = str(relation["subjectLineageId"]), str(relation["objectLineageId"])
        subject, target = references.get(subject_id, {}), references.get(target_id, {})
        features = link_features(float(relation["score"]), subject, target, concepts_by_reference.get(subject_id, ()),
                                 concepts_by_reference.get(target_id, ()))
        examples.append(LearningExample(
            f"link-{relation.get('id') or subject_id + '-' + target_id}", iso_day(metadata.get("decidedAt") or relation.get("updatedAt")),
            metadata["decision"] == "accepted", explanation_of(metadata.get("reasonCode"), metadata.get("note")), features,
            f"{subject.get('title') or subject_id} <-> {target.get('title') or target_id}", str(target.get("sourceUri") or ""),
            f"Suggested link, similarity {features['similarity']:.3f}.", {"source": LINK_SOURCE, "relationId": relation.get("id"),
                                                                         "decidedAt": iso_day(metadata.get("decidedAt"))}))
    return sorted(examples, key=lambda example: (example.occurred_at, example.example_id))


def load_link_examples(client: Any, corpus_id: str) -> list[LearningExample]:
    from .reference_links import REFERENCE_LINK_FEED_KEY

    rows = client.list_by_index(FEED_INDEX, REFERENCE_LINK_FEED_KEY)
    references = {str(reference["lineageId"]): reference for reference in client.list_records("Reference")
                  if reference.get("corpusId") == corpus_id and reference.get("versionState") == "current"}
    concepts: dict[str, set[str]] = {}
    for relation in rows:
        if relation.get("objectKind") == "semanticNode" and relation.get("relationState") == "current":
            concepts.setdefault(str(relation["subjectLineageId"]), set()).add(str(relation["objectLineageId"]))
    return link_examples([relation for relation in rows if str(relation.get("subjectLineageId")) in references], references, concepts)


# --- idea-pack-fit -------------------------------------------------------------------------------------------------------------


def idea_decision(item: Mapping[str, Any], generated: Mapping[str, Any]) -> dict[str, Any] | None:
    """``{positive, reason, by, at}`` for an idea a person decided: the editor's move forward or to spiked, else ``generated.decision``."""
    from .ideas.labels import decision_of

    recorded = generated.get("decision") if isinstance(generated.get("decision"), dict) else {}
    moved = decision_of(dict(item))
    if moved is not None:
        return {"positive": moved["label"] == "include", "by": moved["by"], "at": moved["at"],
                "reason": explanation_of(recorded.get("reasonCode"), recorded.get("note") or moved["reason"])}
    if recorded.get("decision") in ("accepted", "rejected"):
        return {"positive": recorded["decision"] == "accepted", "by": str(recorded.get("decidedBy") or ""),
                "at": recorded.get("decidedAt") or "", "reason": explanation_of(recorded.get("reasonCode"), recorded.get("note"))}
    return None


def _person(actor: str) -> bool:
    return (not machine_story_actor(actor)) or actor == "papyrus-cli"


def pack_features(evidence: Mapping[str, Any], idea_created_at: Any, ideas_on_anchor: Sequence[Any],
                  edges: Sequence[Mapping[str, Any]], message_count: int) -> dict[str, Any]:
    members = {str(lineage) for lineage in evidence.get("referenceLineageIds") or []}
    inside = [edge for edge in edges if str(edge.get("subject")) in members and str(edge.get("object")) in members]
    created = _moment(idea_created_at)
    earlier = [moment for moment in map(_moment, ideas_on_anchor) if moment and created and moment < created]
    return {
        "signal": str(evidence.get("signal") or ""),
        "surprise": float(evidence.get("surprise") or 0.0),
        "packSize": len(members),
        "humanConfirmedEdgeShare": (sum(1 for edge in inside if edge.get("humanDecided")) / len(inside)) if inside else 0.0,
        "messageCount": message_count,
        "daysSinceLastIdeaOnAnchor": (created - max(earlier)).days if earlier else None,
    }


def pack_examples(ideas: Sequence[tuple[Mapping[str, Any], Mapping[str, Any]]], edges: Sequence[Mapping[str, Any]] = (),
                  message_counts: Mapping[str, int] | None = None) -> list[LearningExample]:
    """One example per generated idea a person decided and that records the pack it came from (``generated.evidence.packId``)."""
    anchors: dict[str, list[Any]] = {}
    for item, generated in ideas:
        anchor = (generated.get("evidence") or {}).get("anchor")
        if anchor:
            anchors.setdefault(str(anchor), []).append(item.get("versionCreatedAt") or item.get("createdAt"))
    examples = []
    for item, generated in ideas:
        evidence = generated.get("evidence") or {}
        decision = idea_decision(item, generated)
        if not evidence.get("packId") or decision is None or not _person(str(decision["by"])):
            continue
        created = item.get("versionCreatedAt") or item.get("createdAt")
        features = pack_features(evidence, created, anchors.get(str(evidence.get("anchor")), []), edges,
                                 int((message_counts or {}).get(str(evidence.get("anchor")), 0)))
        examples.append(LearningExample(
            f"pack-{evidence['packId']}-{item.get('lineageId') or item['id']}", iso_day(decision["at"]), decision["positive"],
            str(decision["reason"]), features, str(item.get("title") or ""), "",
            f"Pack {evidence['packId']} from the {features['signal']} signal.",
            {"source": PACK_SOURCE, "packId": evidence["packId"], "decidedAt": iso_day(decision["at"])}))
    return sorted(examples, key=lambda example: (example.occurred_at, example.example_id))


def load_pack_examples(client: Any, corpus_id: str | None = None) -> list[LearningExample]:
    from .ideas.items import generated_of
    from .reference_links import REFERENCE_LINK_FEED_KEY
    from .story_from_reference import _current_versions

    ideas = [(item, generated) for item in _current_versions(client.list_records("Item")) if (generated := generated_of(item)) is not None]
    edges = [{"subject": relation["subjectLineageId"], "object": relation["objectLineageId"],
              "humanDecided": human_actor(str(_metadata(relation).get("decidedBy") or ""))}
             for relation in client.list_by_index(FEED_INDEX, REFERENCE_LINK_FEED_KEY)
             if relation.get("objectKind") == "reference" and relation.get("relationState") == "current"]
    return pack_examples(ideas, edges)


# --- training split and export -------------------------------------------------------------------------------------------------


def split_chronologically(examples: Sequence[LearningExample], held_out_share: float = DEFAULT_HELD_OUT_SHARE
                          ) -> tuple[list[LearningExample], list[LearningExample]]:
    """Earlier decisions train, the latest ``held_out_share`` are held out, so a trained version is always judged on decisions it never saw."""
    if not 0.0 < held_out_share < 1.0:
        raise ValueError("held_out_share must be above 0 and below 1.")
    ordered = sorted(examples, key=lambda example: (example.occurred_at, example.example_id))
    held = math.ceil(len(ordered) * held_out_share) if len(ordered) >= 2 else 0
    return ordered[: len(ordered) - held], ordered[len(ordered) - held:]


CLASSIFIER_LABELS = {LINK_CLASSIFIER_ID: (LINK_POSITIVE_LABEL, LINK_LABELS[1]), PACK_CLASSIFIER_ID: (PACK_POSITIVE_LABEL, PACK_LABELS[1])}


def example_rows(classifier_id: str, examples: Iterable[LearningExample]) -> list[dict[str, Any]]:
    positive, negative = CLASSIFIER_LABELS[classifier_id]
    return [example.as_row(classifier_id, positive, negative) for example in examples]


# --- evaluation and promotion --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PromotionEvaluation:
    classifier_id: str
    metric: str
    held_out: int
    rule_score: float | None
    trained_score: float | None
    trained_only_right: int
    rule_only_right: int
    p_value: float | None
    promoted: bool
    reason: str

    def record(self) -> dict[str, Any]:
        return {"classifierId": self.classifier_id, "metric": self.metric, "heldOut": self.held_out, "ruleScore": self.rule_score,
                "trainedScore": self.trained_score, "trainedOnlyRight": self.trained_only_right, "ruleOnlyRight": self.rule_only_right,
                "pValue": self.p_value, "promoted": self.promoted, "reason": self.reason}


def sign_test_p_value(wins: int, losses: int) -> float:
    """One-sided exact probability of at least ``wins`` wins among ``wins + losses`` decided comparisons if the two were equally good."""
    total = wins + losses
    return sum(math.comb(total, k) for k in range(wins, total + 1)) / 2 ** total if total else 1.0


def _verdict(classifier_id: str, metric: str, held_out: int, rule_score: float | None, trained_score: float | None, wins: int, losses: int,
             cannot: str | None = None) -> PromotionEvaluation:
    if cannot:
        return PromotionEvaluation(classifier_id, metric, held_out, rule_score, trained_score, wins, losses, None, False, cannot)
    p_value = sign_test_p_value(wins, losses)
    promoted = wins > losses and p_value <= SIGNIFICANCE
    reason = ("the trained version beats the statistical rule on held-out decisions" if promoted
              else f"the trained version does not beat the statistical rule (wins {wins}, losses {losses}, p {p_value:.3f})")
    return PromotionEvaluation(classifier_id, metric, held_out, rule_score, trained_score, wins, losses, p_value, promoted, reason)


def _missing(held_out: Sequence[LearningExample], probabilities: Mapping[str, float]) -> list[str]:
    return [example.example_id for example in held_out if example.example_id not in probabilities]


def evaluate_link_fit(train: Sequence[LearningExample], held_out: Sequence[LearningExample], probabilities: Mapping[str, float],
                      precision: float = DEFAULT_PRECISION) -> PromotionEvaluation:
    """Accuracy on held-out suggestions: the Wilson cut learned from the training split against the trained version at probability 0.5."""
    metric = "accuracy"
    if not held_out:
        return _verdict(LINK_CLASSIFIER_ID, metric, 0, None, None, 0, 0, "no held-out decisions yet")
    if _missing(held_out, probabilities):
        return _verdict(LINK_CLASSIFIER_ID, metric, len(held_out), None, None, 0, 0, "the trained version has no prediction for every held-out decision")
    cut = calibrate_kind([(float(example.features["similarity"]), example.positive) for example in train], precision).threshold
    rule_right = [(cut is not None and example.features["similarity"] >= cut) == example.positive for example in held_out]
    trained_right = [(probabilities[example.example_id] >= 0.5) == example.positive for example in held_out]
    wins = sum(1 for trained, rule in zip(trained_right, rule_right) if trained and not rule)
    losses = sum(1 for trained, rule in zip(trained_right, rule_right) if rule and not trained)
    return _verdict(LINK_CLASSIFIER_ID, metric, len(held_out), sum(rule_right) / len(held_out), sum(trained_right) / len(held_out), wins, losses)


def evaluate_pack_fit(held_out: Sequence[LearningExample], probabilities: Mapping[str, float]) -> PromotionEvaluation:
    """Pairwise ordering on held-out ideas: how often a moved-forward idea's pack is ranked above a spiked one's, by surprise and by the trained version."""
    metric = "pairwise ordering"
    positives = [example for example in held_out if example.positive]
    negatives = [example for example in held_out if not example.positive]
    if not positives or not negatives:
        return _verdict(PACK_CLASSIFIER_ID, metric, len(held_out), None, None, 0, 0, "held-out decisions need both forwarded and spiked ideas")
    if _missing(held_out, probabilities):
        return _verdict(PACK_CLASSIFIER_ID, metric, len(held_out), None, None, 0, 0, "the trained version has no prediction for every held-out decision")
    wins = losses = 0
    rule_credit = trained_credit = 0.0
    for good in positives:
        for bad in negatives:
            rule_order = good.features["surprise"] - bad.features["surprise"]
            trained_order = probabilities[good.example_id] - probabilities[bad.example_id]
            rule_credit += 1.0 if rule_order > 0 else 0.5 if rule_order == 0 else 0.0
            trained_credit += 1.0 if trained_order > 0 else 0.5 if trained_order == 0 else 0.0
            wins += 1 if trained_order > 0 and rule_order <= 0 else 0
            losses += 1 if rule_order > 0 and trained_order <= 0 else 0
    pairs = len(positives) * len(negatives)
    return _verdict(PACK_CLASSIFIER_ID, metric, len(held_out), rule_credit / pairs, trained_credit / pairs, wins, losses)


def promotion_path(store_directory: str | Path) -> Path:
    return Path(store_directory) / PROMOTION_FILE_NAME


def _read_promotions(store_directory: str | Path) -> dict[str, Any]:
    path = promotion_path(store_directory)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def is_promoted(store_directory: str | Path, classifier_id: str) -> bool:
    """The promotion flag: off unless the latest recorded evaluation promoted the classifier."""
    return bool(_read_promotions(store_directory).get(classifier_id, {}).get("promoted"))


def record_evaluation(store_directory: str | Path, evaluation: PromotionEvaluation, now: str) -> None:
    promotions = _read_promotions(store_directory)
    promotions[evaluation.classifier_id] = {**evaluation.record(), "evaluatedAt": now}
    path = promotion_path(store_directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(promotions, indent=2, sort_keys=True), encoding="utf-8")


# --- consumers: switch only when promoted --------------------------------------------------------------------------------------


class PromotedLinkCalibration:
    """A ``SuggestionCalibration`` whose likely/possible marks come from the trained version only when ``reference-link-fit`` is promoted.

    ``probability_of`` takes a kept neighbour (``lineageId``, ``similarity``, ``metadata``) and returns the trained probability that an editor accepts it.
    The cut and the record stay the Wilson rule's."""

    def __init__(self, rule: Any, promoted: bool, probability_of: Callable[[Mapping[str, Any]], float] | None):
        self.rule, self.promoted, self.probability_of = rule, promoted, probability_of

    def label(self, kind: str, similarity: float) -> str | None:
        return self.rule.label(kind, similarity)

    def label_candidate(self, kind: str, candidate: Mapping[str, Any]) -> str | None:
        if not self.promoted or self.probability_of is None or kind != REFERENCE_KIND:
            return self.rule.label(kind, candidate["similarity"])
        return "likely" if self.probability_of(candidate) >= 0.5 else "possible"

    def cut(self, kind: str, knee: Callable[[list[float]], int]) -> Callable[[list[float]], int] | None:
        return self.rule.cut(kind, knee)

    def record(self) -> dict[str, Any]:
        return {**self.rule.record(), "linkFitPromoted": self.promoted}


def order_packs(packs: Sequence[Any], promoted: bool, probability_of: Callable[[Any], float] | None) -> list[Any]:
    """The queue order of packs: the trained version's, best first, only when ``idea-pack-fit`` is promoted; otherwise the given (surprise) order."""
    if not promoted or probability_of is None:
        return list(packs)
    return sorted(packs, key=lambda pack: -probability_of(pack))
