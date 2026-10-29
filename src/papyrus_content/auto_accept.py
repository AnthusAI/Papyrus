"""Automatic acceptance of confident, unvoted References: on by default per publication (``autoAccept: {"enabled": false}`` turns it off), learned from the editors' own votes, audited and reversible.

A monitor delivers each Reference as ``pending`` with the Cyclotron's verdict (the ``relevance_decision_is`` relation: label and confidence).
Editors Accept or Reject. This pass accepts a pending Reference on its own when all three hold:

* **Positive verdict.** The Cyclotron's current verdict is the publication's positive label.
* **Confident enough, learned per publication.** The threshold ``t`` is the smallest verdict confidence for which, among References an editor
  voted on whose verdict was positive and at least ``t`` sure, the Wilson 95% lower bound of the share the editor accepted is at least the
  target precision (a policy setting, default 0.9). With too few votes, or votes that disagree too much, no ``t`` qualifies and nothing is
  accepted; the reason is recorded.
* **Nobody voted in the time editors normally take, learned per publication.** The delay is the ``q``-quantile (a policy setting, default 0.9)
  of the time from delivery (``createdAt``) to a human vote, over the publication's human votes. Without any, nothing is accepted.

Nothing here is a fixed cap or window. The write is the same record shape an editor's accept leaves, except that ``curationStatusUpdatedBy`` is
``auto:cyclotron`` (not a person, so the router never sends it to the Cyclotron as an editor's label) and a curation Message whose
``actorKind`` is ``cyclotron``. An editor can Reject or re-Accept it later; that is then an ordinary human vote. A Reference an editor
touched is never changed. A monitor that delivers by a fixed rule (``decisions: "direct"``) has no confidence: its delivery is accepted on delivery by ``auto:rule``. See docs/monitoring-cloud.md#automatic-acceptance.
"""
from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .catalog import semantic_relation_record
from .ideas.digest import parse_time, relations_of, relevance_of
from .ids import hash_short, safe_id

AUTO_ACTOR = "auto:cyclotron"
RULE_ACTOR = "auto:rule"   # a monitor with a fixed delivery rule (decisions "direct") has no confidence: matching the rule is the acceptance
RULE_ACTOR_KIND = "rule"
ACTOR_LABEL = "Cyclotron (automatic)"
RULE_ACTOR_LABEL = "Monitor rule (automatic)"
CYCLOTRON_CURATION_ACTOR_KIND = "cyclotron"
DEFAULT_PRECISION = 0.9
DEFAULT_LATENCY_QUANTILE = 0.9
WILSON_Z = 1.96   # two-sided 95%
POLICY_KEYS = ("enabled", "precision", "latencyQuantile")
REVIEWED_FEED_KEY = "references#reviewed"


def is_auto_actor(actor: Any) -> bool:
    return str(actor or "").strip() in (AUTO_ACTOR, RULE_ACTOR)


def validate_auto_accept(publication_id: str, raw: Any) -> dict[str, Any] | None:
    """The normalized ``autoAccept`` policy of a router publication. Absent means ON with the defaults; ``{"enabled": false}`` turns it off."""
    if raw is None:
        return {"enabled": True, "precision": DEFAULT_PRECISION, "latencyQuantile": DEFAULT_LATENCY_QUANTILE}
    if not isinstance(raw, dict):
        raise ValueError(f"router publication {publication_id} has an invalid autoAccept (an object is needed)")
    unknown = sorted(set(raw) - set(POLICY_KEYS))
    if unknown:
        raise ValueError(f"router publication {publication_id} autoAccept has unknown keys: {', '.join(unknown)}")
    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError(f"router publication {publication_id} autoAccept.enabled must be true or false")
    precision = raw.get("precision", DEFAULT_PRECISION)
    quantile = raw.get("latencyQuantile", DEFAULT_LATENCY_QUANTILE)
    for name, value, low, high in (("precision", precision, 0.0, 1.0), ("latencyQuantile", quantile, 0.0, 1.0)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low < value < high:
            raise ValueError(f"router publication {publication_id} autoAccept.{name} must be a number above 0 and below 1")
    return {"enabled": enabled, "precision": float(precision), "latencyQuantile": float(quantile)}


# --- what is learned -----------------------------------------------------------------------------------------------------------


def wilson_lower_bound(successes: int, total: int, z: float = WILSON_Z) -> float:
    """The Wilson score interval's lower bound for ``successes`` of ``total`` (0 when there are no trials)."""
    if total <= 0:
        return 0.0
    share = successes / total
    denominator = 1 + z * z / total
    centre = share + z * z / (2 * total)
    margin = z * math.sqrt((share * (1 - share) + z * z / (4 * total)) / total)
    return max(0.0, (centre - margin) / denominator)


def learn_threshold(votes: Sequence[tuple[float, bool]], precision: float) -> dict[str, Any]:
    """The smallest confidence ``t`` whose voted positives at or above it have a Wilson lower bound of the accept rate >= ``precision``.

    ``votes`` pairs a positive verdict's confidence with whether the editor accepted. Returns ``{"threshold", "votes", "accepted", "rate",
    "lowerBound"}`` (the evidence at that threshold), or ``{"threshold": None, "reason", "votes", "bestLowerBound"}`` when none qualifies.
    """
    ordered = sorted(votes, key=lambda vote: vote[0])
    total = len(ordered)
    if total == 0:
        return {"threshold": None, "reason": "no editor votes on positive verdicts yet", "votes": 0, "bestLowerBound": None}
    suffix_accepted = [0] * (total + 1)
    for index in range(total - 1, -1, -1):
        suffix_accepted[index] = suffix_accepted[index + 1] + (1 if ordered[index][1] else 0)
    best = 0.0
    for index, (confidence, _) in enumerate(ordered):
        if index and ordered[index - 1][0] == confidence:
            continue   # a threshold is a distinct confidence; its group starts at its first vote
        n, k = total - index, suffix_accepted[index]
        lower = wilson_lower_bound(k, n)
        best = max(best, lower)
        if lower >= precision:
            return {"threshold": confidence, "votes": n, "accepted": k, "rate": k / n, "lowerBound": lower}
    return {"threshold": None, "votes": total, "bestLowerBound": round(best, 4),
            "reason": f"no confidence reaches the target precision {precision:.0%}: {total} editor votes on positive verdicts, best 95% lower bound {best:.1%}"}


def quantile(values: Sequence[float], q: float) -> float | None:
    """The nearest-rank ``q``-quantile (the smallest value at least ``q`` of the values are at or below), None without values."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1))]


# --- reading a publication -----------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Verdict:
    positive: bool
    confidence: float | None


def verdict_of(client: Any, reference: Mapping[str, Any], positive_label: str) -> Verdict | None:
    """The Cyclotron's current verdict on a Reference: whether it is the positive label and how sure. None when it has none."""
    decision = relevance_of(relations_of(client, dict(reference)))
    if decision is None:
        return None
    confidence = decision.get("confidence")
    if confidence is None:
        confidence = decision.get("score")   # for a positive label the score is the positive probability
    return Verdict(decision.get("label") == (decision.get("positiveLabel") or positive_label), confidence)


def current_references(client: Any, corpus_id: str, status: str) -> list[dict[str, Any]]:
    rows = client.list_by_index("referencesByCurationStatusKey", f"{corpus_id}#{status}")
    return [row for row in rows if row and row.get("versionState", "current") == "current"]


def age_seconds(start: Any, end: datetime) -> float | None:
    moment = parse_time(str(start or ""))
    return None if moment is None else (end - moment).total_seconds()


def reason_text(*, confidence: float, learned: Mapping[str, Any], precision: float, delay_seconds: float, quantile_: float) -> str:
    days = delay_seconds / 86400
    wait = f"{days:.1f} days" if days >= 1 else f"{delay_seconds / 3600:.1f} hours"
    return (f"Accepted automatically by the Cyclotron: it was {confidence:.1%} sure this is relevant, at or above the {learned['threshold']:.1%} "
            f"learned from {learned['votes']} editor votes (estimated accept rate {learned['rate']:.1%}, 95% lower bound {learned['lowerBound']:.1%}, "
            f"target {precision:.0%}), and nobody voted within {wait}, the {quantile_:.0%} quantile of how long editors take. An editor can still Reject it.")


def accept_reference_automatically(client: Any, reference: Mapping[str, Any], *, reason: str, evidence: Mapping[str, Any], now: str,
                                   actor: str = AUTO_ACTOR) -> bool:
    """Accept one still-pending Reference with an audited curation Message. False when it is no longer pending or an editor touched it."""
    from .monitoring_router import human_actor
    current = client.get_record("Reference", reference["id"])
    if not current or current.get("versionState") != "current" or current.get("curationStatus") != "pending":
        return False
    if human_actor(str(current.get("curationStatusUpdatedBy") or "")):
        return False
    lineage_id = reference.get("lineageId") or reference["id"]
    by_rule = actor == RULE_ACTOR
    message_id = f"message-reference-curation-{safe_id(lineage_id)}-auto-accept-{hash_short([reference['id'], now])}"
    metadata = {"action": "accept", "curationStatus": "accepted", "referenceId": reference["id"], "referenceLineageId": lineage_id,
                "actorKind": RULE_ACTOR_KIND if by_rule else CYCLOTRON_CURATION_ACTOR_KIND, "automatic": True, **evidence}
    client.update_record("Reference", {
        "id": reference["id"], "curationStatus": "accepted", "curationStatusKey": f"{current['corpusId']}#accepted",
        "curationStatusUpdatedAt": now, "curationStatusUpdatedBy": actor, "curationStatusReason": reason,
        "reviewedFeedKey": REVIEWED_FEED_KEY, "updatedAt": now})
    client.upsert("Message", {
        "id": message_id, "messageKind": "reference_curation", "messageDomain": "commentary", "status": "active",
        "summary": f"{current.get('title') or lineage_id}: accepted", "source": "papyrus-monitoring" if by_rule else "cyclotron",
        "authorLabel": RULE_ACTOR_LABEL if by_rule else ACTOR_LABEL,
        "content": reason, "responseTarget": "none", "responseStatus": "COMPLETED", "responseOwner": "papyrus-auto-accept",
        "metadata": json.dumps(metadata, sort_keys=True, default=str), "createdAt": now, "updatedAt": now, "newsroomFeedKey": "messages"})
    relation = semantic_relation_record({
        "predicate": "comment", "subjectKind": "message", "subjectId": message_id, "subjectLineageId": message_id,
        "subjectVersionNumber": 1, "objectKind": "reference", "objectId": reference["id"],
        "objectLineageId": lineage_id, "objectVersionNumber": reference.get("versionNumber"),
        "importedAt": now, "metadata": {"action": "accept", "curationStatus": "accepted",
                                        "messageKind": "reference_curation"}})["expected"]
    client.upsert("SemanticRelation", relation)
    return True


def run_auto_accept(client: Any, publication: Mapping[str, Any], policy: Mapping[str, Any], *, now: datetime, dry_run: bool = False,
                    out_of_time: Callable[[], bool] = lambda: False) -> dict[str, Any]:
    """One pass over one publication. Returns the log record: what was learned, how many candidates, how many accepted, or why it skipped.

    ``publication`` needs ``publicationId``, ``corpusId`` and ``positiveLabel``; ``policy`` is a validated ``autoAccept`` block.
    """
    from .monitoring_router import human_actor
    now = now.astimezone(timezone.utc)
    moment = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    result: dict[str, Any] = {"publicationId": publication["publicationId"], "status": "skipped", "dryRun": dry_run,
                              "targetPrecision": policy["precision"], "latencyQuantile": policy["latencyQuantile"],
                              "threshold": None, "precisionLowerBound": None, "estimatedPrecision": None, "votes": 0,
                              "delaySeconds": None, "latencySamples": 0, "candidates": 0, "accepted": 0, "reason": None}
    corpus_id, positive_label = publication["corpusId"], publication["positiveLabel"]

    voted = [row for status in ("accepted", "rejected") for row in current_references(client, corpus_id, status)
             if human_actor(str(row.get("curationStatusUpdatedBy") or ""))]
    latencies = [seconds for row in voted
                 for seconds in [age_seconds(row.get("createdAt"), parse_time(str(row.get("curationStatusUpdatedAt") or "")) or now)
                                 if row.get("curationStatusUpdatedAt") else None]
                 if seconds is not None and seconds > 0]
    delay = quantile(latencies, policy["latencyQuantile"])
    result.update(latencySamples=len(latencies), delaySeconds=None if delay is None else round(delay))
    if delay is None:
        result["reason"] = "no editor vote latency yet"
        return result

    votes: list[tuple[float, bool]] = []
    for row in voted:
        if out_of_time():
            result["reason"] = "time budget reached while reading editor votes"
            return result
        verdict = verdict_of(client, row, positive_label)
        if verdict is not None and verdict.positive and verdict.confidence is not None:
            votes.append((float(verdict.confidence), row.get("curationStatus") == "accepted"))
    learned = learn_threshold(votes, policy["precision"])
    result.update(votes=learned["votes"], threshold=learned["threshold"])
    if learned["threshold"] is None:
        result.update(reason=learned["reason"], precisionLowerBound=learned["bestLowerBound"])
        return result
    result.update(estimatedPrecision=round(learned["rate"], 4), precisionLowerBound=round(learned["lowerBound"], 4))

    waiting = [row for row in current_references(client, corpus_id, "pending")
               if not human_actor(str(row.get("curationStatusUpdatedBy") or ""))
               and (age_seconds(row.get("createdAt"), now) or -1) >= delay]
    result["status"] = "ran"
    for row in waiting:
        if out_of_time():
            result["reason"] = "time budget reached while reading candidates"
            break
        verdict = verdict_of(client, row, positive_label)
        if verdict is None or not verdict.positive or verdict.confidence is None or verdict.confidence < learned["threshold"]:
            continue
        result["candidates"] += 1
        if dry_run:
            continue
        evidence = {"confidence": float(verdict.confidence), "threshold": learned["threshold"], "estimatedPrecision": learned["rate"],
                    "precisionLowerBound": learned["lowerBound"], "votes": learned["votes"], "targetPrecision": policy["precision"],
                    "delaySeconds": delay, "latencyQuantile": policy["latencyQuantile"]}
        if accept_reference_automatically(client, row, now=moment, evidence=evidence, reason=reason_text(
                confidence=float(verdict.confidence), learned=learned, precision=policy["precision"], delay_seconds=delay,
                quantile_=policy["latencyQuantile"])):
            result["accepted"] += 1
    if dry_run:
        result["status"] = "dry-run"
    return result


# --- monitors that deliver by a fixed rule ---------------------------------------------------------------------------------------


def rule_reason(monitor_id: str, rule_text: str) -> str:
    return (f"Accepted automatically by the {monitor_id} monitor's rule ({rule_text}): it delivers only items that match the rule, so there is no "
            f"relevance prediction and the match is the acceptance. An editor can still Reject it.")


def accept_by_rule(client: Any, reference: Mapping[str, Any], *, monitor_id: str, rule: Any, now: str) -> bool:
    """Accept one just-delivered (still pending) Reference of a ``decisions: "direct"`` monitor, naming the monitor and its rule."""
    from .monitoring_intake import _rule_text
    return accept_reference_automatically(
        client, reference, now=now, actor=RULE_ACTOR, reason=rule_reason(monitor_id, _rule_text(rule)),
        evidence={"monitorId": monitor_id, "rule": rule if isinstance(rule, dict) else None})


def direct_monitors(client: Any, rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """The monitors of a corpus that deliver by rule, with a delivered Reference of each: ``{monitorId: {"rule": ..., "deliveries": n}}``.

    A monitor is a rule monitor when a delivery's provenance relation says ``machineDecision.system == "direct"`` (written since this feature),
    or when none of its deliveries in the corpus carries a Cyclotron verdict at all (a Cyclotron-decided delivery always does)."""
    from .categories_steering import semantic_state_key
    from .ideas.monitor_stories import monitor_of
    seen: dict[str, dict[str, Any]] = {}
    for row in rows:
        lineage = row.get("lineageId") or row["id"]
        incoming = list(client.list_semantic_relations_by_object_state(semantic_state_key("reference", lineage)))
        monitor = monitor_of(incoming)
        if monitor is None:
            continue
        entry = seen.setdefault(monitor, {"rule": None, "flagged": False, "verdicts": 0, "deliveries": 0})
        entry["deliveries"] += 1
        for relation in incoming:
            metadata = relation.get("metadata")
            metadata = json.loads(metadata) if isinstance(metadata, str) else (metadata or {})
            decision = metadata.get("machineDecision") if isinstance(metadata, dict) else None
            if isinstance(decision, dict) and decision.get("system") == "direct":
                entry["flagged"], entry["rule"] = True, decision.get("rule")
        if relevance_of(relations_of(client, dict(row))) is not None:
            entry["verdicts"] += 1
    return {monitor: {"rule": entry["rule"], "deliveries": entry["deliveries"]} for monitor, entry in seen.items()
            if entry["flagged"] or entry["verdicts"] == 0}


def run_rule_backfill(client: Any, publication: Mapping[str, Any], *, now: datetime, dry_run: bool = False) -> dict[str, Any]:
    """Accept the pending deliveries of the publication's rule monitors that no editor touched (the CLI's backfill for deliveries made before this existed)."""
    from .categories_steering import semantic_state_key
    from .ideas.monitor_stories import monitor_of
    from .monitoring_router import human_actor
    moment = now.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    corpus_id = publication["corpusId"]
    everything = [row for status in ("pending", "accepted", "rejected") for row in current_references(client, corpus_id, status)]
    monitors = direct_monitors(client, everything)
    result: dict[str, Any] = {"publicationId": publication["publicationId"], "status": "dry-run" if dry_run else "ran", "dryRun": dry_run,
                              "mode": "rule", "monitors": sorted(monitors), "candidates": 0, "accepted": 0, "references": []}
    for row in current_references(client, corpus_id, "pending"):
        if human_actor(str(row.get("curationStatusUpdatedBy") or "")):
            continue
        lineage = row.get("lineageId") or row["id"]
        monitor = monitor_of(list(client.list_semantic_relations_by_object_state(semantic_state_key("reference", lineage))))
        if monitor not in monitors:
            continue
        result["candidates"] += 1
        result["references"].append({"referenceId": row["id"], "title": row.get("title"), "monitorId": monitor})
        if not dry_run and accept_by_rule(client, row, monitor_id=monitor, rule=monitors[monitor]["rule"], now=moment):
            result["accepted"] += 1
    return result
