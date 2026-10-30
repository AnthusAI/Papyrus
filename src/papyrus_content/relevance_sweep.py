"""The decide-relevance sweep: the candidate pipeline's hook into the cyclotron.

One sweep, run by a worker after research intake and on a schedule:

1. Claims the publication's ``cyclotron.relevance`` Assignment (one writer).
2. Restores the cyclotron store from the private media bucket when this worker
   has no local copy.
3. Primes the running cyclotron with the URLs editors pasted in the Newsroom
   (priming requests), then sends editors' reviews of decided references
   back to it, using the existing ``reference_curation`` Messages and
   scope-training rule.
4. Decides every current pending ``Reference`` of the canonical corpus and
   records each new decision as a ``relevance_decision_is`` relation.
5. Records the ``cyclotron-status/v1`` snapshot, saves the store to the
   private bucket, and releases the claim.

It changes a Reference's curation status only through the opt-in, audited
auto-reject of clear misses (auto_reject.py). Nothing runs between sweeps:
the worker, the store and the bucket all scale to zero.
"""
from __future__ import annotations

import asyncio
import json
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .auto_decision_gate import auto_decision_gate, load_approved_proof
from .auto_reject import clear_miss_probability, reject_reference_automatically
from .assignments import active_claim_held_by_different_assignee, apply_assignment_action
from .ids import knowledge_corpus_id, safe_id
from .model_attachments import download_attachment_buffer, expand_private_payload_records, parse_jsonish
from .records import apply_record_changes, build_record_change_from_current
from .reference_policy import normalize_reference_curation_status
from .relevance_cyclotron import (RelevanceCyclotronPlan, build_relevance_cyclotron, decision_model_from_environment,
                                  optimizer_from_environment)
from .relevance_priming import (MAX_TRANSIENT_ATTEMPTS, PRIMING_ATTEMPTS_ROLE, PRIMING_OUTCOME_ROLE, TRANSIENT_GIVE_UP_MESSAGE,
                                UNREADABLE_MESSAGE, grobid_is_alive, priming_attempts_record, PRIMING_REQUEST_KIND, ExtractUrl, default_url_extractor,
                                normalize_priming_url, priming_item_id, priming_label, priming_outcome_record,
                                readable_engine_refusal)
from .reference_vote import latest_vote
from .relevance_decisions import (RELEVANCE_RELATION, curation_was_made_by_a_human, current_relevance_decision, relevance_decision_records,
                                  human_label_for_review, relevance_label_for_review, review_rate_request_id, status_snapshot_record)
from .relevance_shadow import (USAGE_PAYLOAD_KIND, comparison_of_suggestion_with_human_decision,
                               decisions_remaining_today, live_agreement, reproducibility_provenance,
                               shadow_agreement_record, usage_record, utc_day)
from .relevance_sample import distribution, draw_sample, load_manifest, write_manifest
from .steering import relevance_corpus_key, require_corpus_config

SWEEP_ASSIGNMENT_TYPE = "cyclotron.relevance"
SNAPSHOT_NAME = "state.tar.gz"
REVIEWED_STATUSES = ("accepted", "rejected", "archived")


class CyclotronClaimed(RuntimeError):
    """Another worker holds the relevance cyclotron's Assignment claim."""


@dataclass
class SweepResult:
    applied: bool
    pending: list[str] = field(default_factory=list)
    decided: int = 0
    primed: int = 0
    priming_failed: int = 0
    priming_retrying: int = 0
    reviews: int = 0
    primed_from_human_reviews: int = 0
    retired_labels: int = 0
    stopped_because: str | None = None
    live_agreement: dict[str, Any] | None = None
    status: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
    classifier_set: dict[str, Any] | None = None
    auto_rejected: list[dict[str, Any]] = field(default_factory=list)
    sample: dict[str, Any] | None = None

    def to_json(self) -> dict[str, Any]:
        return {"applied": self.applied, "pendingReferences": self.pending, "decided": self.decided,
                "primed": self.primed, "primingFailed": self.priming_failed, "primingRetrying": self.priming_retrying, "reviewsSent": self.reviews, "primedFromHumanReviews": self.primed_from_human_reviews, "retiredLabels": self.retired_labels, "autoRejected": self.auto_rejected, "stoppedBecause": self.stopped_because,
                "liveAgreement": self.live_agreement, "status": self.status, "warnings": self.warnings,
                **({"classifierSet": self.classifier_set} if self.classifier_set is not None else {}),
                **({"sample": self.sample} if self.sample is not None else {})}


class S3SnapshotStore:
    """The store snapshot in the private media bucket (standard AWS credential chain)."""

    def __init__(self, client=None):
        if client is None:
            import boto3
            client = boto3.client("s3")
        self.client = client

    @staticmethod
    def _split(uri: str) -> tuple[str, str]:
        bucket, _, key = uri.removeprefix("s3://").partition("/")
        return bucket, key

    def download(self, uri: str, path: Path) -> bool:
        bucket, key = self._split(uri)
        try:
            self.client.download_file(bucket, key, str(path))
        except Exception as error:  # botocore ClientError for a missing object
            if "404" in str(error) or "Not Found" in str(error) or "NoSuchKey" in str(error):
                return False
            raise
        return True

    def upload(self, path: Path, uri: str) -> None:
        bucket, key = self._split(uri)
        self.client.upload_file(str(path), bucket, key, ExtraArgs={"ServerSideEncryption": "AES256"})


class AssignmentClaimLease:
    """The Cyclotron SDK lease, held as an exclusive claim on the sweep Assignment."""

    def __init__(self, client, assignment_id: str, worker: str, *, ttl_seconds: int = 3600):
        self.client, self.assignment_id, self.worker, self.ttl_seconds = client, assignment_id, worker, ttl_seconds
        self.held = False

    def acquire(self) -> None:
        current = self.client.get_record("Assignment", self.assignment_id)
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        if current and active_claim_held_by_different_assignee(current, self.worker, now):
            raise CyclotronClaimed(f"The relevance cyclotron is claimed by {current.get('assigneeKey')}.")
        apply_assignment_action(self.client, auth_claims={}, action="claim", assignment_id=self.assignment_id,
                                options={"assignee-key": self.worker, "claim-ttl-seconds": self.ttl_seconds},
                                actor_label=self.worker)
        self.held = True

    def release(self) -> None:
        if self.held:
            apply_assignment_action(self.client, auth_claims={}, action="release", assignment_id=self.assignment_id,
                                    options={"assignee-key": self.worker}, actor_label=self.worker)
            self.held = False


class _HeldLease:
    """The sweep holds the claim for its whole run; the SDK must not take it twice."""

    def acquire(self) -> None:
        pass

    def release(self) -> None:
        pass


def sweep_assignment_id(cyclotron_id: str) -> str:
    return f"assignment-{safe_id(SWEEP_ASSIGNMENT_TYPE)}-{safe_id(cyclotron_id)}"


def ensure_sweep_assignment(client, plan: RelevanceCyclotronPlan, corpus_id: str, now: str) -> str:
    assignment_id = sweep_assignment_id(plan.definition.id)
    if client.get_record("Assignment", assignment_id) is None:
        queue_key = f"{SWEEP_ASSIGNMENT_TYPE}#{corpus_id}"
        client.upsert("Assignment", {
            "id": assignment_id, "assignmentTypeKey": SWEEP_ASSIGNMENT_TYPE, "queueKey": queue_key,
            "queueStatusKey": f"{queue_key}#open", "status": "open", "priority": 50,
            "title": f"Relevance cyclotron sweep ({plan.definition.id})",
            "brief": "Decide pending candidate references and send editors' reviews to the relevance cyclotron.",
            "corpusId": corpus_id, "createdBy": "papyrus-cyclotron", "createdAt": now, "updatedAt": now,
            "newsroomFeedKey": "assignments",
        })
    return assignment_id


def reference_item(reference: Mapping[str, Any], *, source_content: Mapping[str, str] | None = None):
    """The cyclotron item for a candidate reference: what an editor sees when deciding."""
    from decision_flywheel import Item

    reference = {**reference, **({"title": source_content["title"]} if source_content else {})}
    source = reference.get("sourceUri") or ""
    domain = source.split("//", 1)[-1].split("/", 1)[0] if "//" in source else ""
    lines = [reference.get("title") or reference.get("externalItemId") or reference["lineageId"]]
    if domain:
        lines.append(f"Source: {domain}")
    if reference.get("sourcePublishedAt"):
        lines.append(f"Published: {str(reference['sourcePublishedAt'])[:10]}")
    elif source_content:
        lines.append("Source publication date: unknown")
        if reference.get("importedAt"):
            lines.append(f"Reference intake date: {str(reference['importedAt'])[:10]}")
    # The intake reason describes the staged catalog row, before extraction.
    # Keep it in raw provenance, not in the completed priming model projection.
    if not source_content and reference.get("curationStatusReason"):
        lines.append(f"Why it was proposed: {reference['curationStatusReason']}")
    if source_content:
        lines.append(source_content["abstract"])
    values = {"text": "\n".join(str(line) for line in lines), "title": reference.get("title"),
              "source_uri": source or None, "domain": domain or None,
              "published_at": reference.get("sourcePublishedAt"),
              "ingestion_rationale": reference.get("curationStatusReason") if not source_content else None}
    if source_content:
        values["abstract"] = source_content["abstract"]
    return Item(reference.get("lineageId") or reference["id"], {key: value for key, value in values.items() if value})


def run_decide_relevance(client, steering_config: Mapping[str, Any], doctrine, *, apply: bool, worker: str,
                         max_count: int | None = None, model=None, optimizer=None, snapshots=None,
                         now: Callable[[], str] | None = None, priming_snapshot=None,
                         extract_url: ExtractUrl | None = None,
                         grobid_alive: Callable[[], bool] | None = None,
                         sample_size: int | None = None, sample_seed: str | None = None,
                         sample_manifest: Mapping[str, Any] | None = None,
                         include_housekeeping: bool = False) -> SweepResult:
    """Run one sweep; an explicit accepted priming snapshot seeds a new store only.

    Editors' priming requests are applied to the running store whatever the
    snapshot; ``extract_url`` turns a pasted URL into item values and defaults
    to the existing Papyrus priming curation. ``grobid_alive`` is the liveness
    preflight run before any priming request is extracted; it defaults to a
    real check only with the default extractor.

    Omitting priming_snapshot preserves normal operation. Models/optimizers and
    snapshot transport still default to the configured providers.

    The references decided are the pending ones of ``relevanceCyclotron.corpusKey``
    (else the canonical corpus). By default they are every pending reference,
    oldest first. ``sample_size`` with ``sample_seed`` decides a deterministic
    spread sample instead (relevance_sample.py); ``sample_manifest`` decides
    exactly the references of an earlier draw that are still pending. A sample
    never re-decides a reference that already has a current relevance decision,
    so repeated batches under ``max_count`` walk through it without paying twice.
    """
    now = now or (lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    plan = build_relevance_cyclotron(steering_config, doctrine)
    priming_examples = priming_snapshot.for_definition(plan.definition) if priming_snapshot is not None else None
    canonical_corpus = require_corpus_config(dict(steering_config), steering_config["canonicalTopicSet"]["corpusKey"],
                                             "canonicalTopicSet.corpusKey")
    corpus = require_corpus_config(dict(steering_config), relevance_corpus_key(steering_config),
                                   "relevanceCyclotron.corpusKey")
    corpus_id = knowledge_corpus_id(corpus)
    pending = _current(client.list_by_index("referencesByCurationStatusKey", f"{corpus_id}#pending"))
    pending.sort(key=lambda reference: str(reference.get("importedAt") or reference.get("createdAt") or ""))
    sample = None
    if sample_size is not None or sample_manifest is not None:
        pending, sample = _sampled(client, pending, corpus_id, sample_size, sample_seed, sample_manifest,
                                   include_housekeeping)
    if max_count is not None:
        pending = pending[:max_count]
    if priming_examples is not None:
        example_ids = {row.item.id for rows in priming_examples.values() for row in rows}
        if any(reference_item(reference).id in example_ids for reference in pending):
            raise ValueError("priming and operational reference identities must be disjoint")
    result = SweepResult(applied=apply, sample=sample)
    if not plan.enabled:
        result.stopped_because = "disabled"
        result.warnings.append(f"{plan.definition.id} is switched off in the steering config; nothing was decided.")
        if apply:
            result.live_agreement = _live_agreement(client, plan, corpus_id, now(), result.stopped_because)
            _apply(client, [shadow_agreement_record(plan.definition.id, result.live_agreement, now=now())])
        return result
    today = utc_day(now())
    recorded_usage = _recorded_usage(client, plan.definition.id)
    decisions_allowed = decisions_remaining_today(recorded_usage, maximum_per_day=plan.max_decisions_per_day, today=today)
    result.pending = [reference["lineageId"] for reference in pending]
    if not apply:
        result.auto_rejected = _auto_rejections_a_sweep_would_make(client, plan, corpus_id, pending, now())
        return result

    from .editorial_model_context import classification_model
    model = classification_model(model if model is not None else decision_model_from_environment(plan),
                                 client, steering_config)
    model.verify_context()

    from decision_flywheel import Cyclotron

    assignment_id = ensure_sweep_assignment(client, plan, corpus_id, now())
    lease = AssignmentClaimLease(client, assignment_id, worker)
    lease.acquire()
    try:
        snapshots = snapshots if snapshots is not None else (S3SnapshotStore() if plan.s3_prefix else None)
        local = Path(plan.local_path)
        snapshot_uri = f"{plan.s3_prefix.rstrip('/')}/{SNAPSHOT_NAME}" if plan.s3_prefix else None
        if snapshots and snapshot_uri and not (local / "cyclotron.sqlite3").exists():
            with tempfile.TemporaryDirectory() as scratch:
                archive = Path(scratch) / SNAPSHOT_NAME
                if snapshots.download(snapshot_uri, archive):
                    Cyclotron.restore(archive, local, lease=_HeldLease())
        optimizer = optimizer if optimizer is not None else optimizer_from_environment(plan)
        cyclotron = Cyclotron.open(local, plan.definition, model, optimizer, lease=_HeldLease(),
                                   max_requests=plan.max_requests, review_program=plan.review_program,
                                   seed_rubrics=plan.seed_rubrics,
                                   **({'priming_examples':priming_examples} if priming_examples is not None else {}))
        try:
            _apply_review_rate_request(client, cyclotron, plan, result.warnings)
            records = _apply_priming_requests(
                client, cyclotron, plan, extract_url or default_url_extractor(steering_config, canonical_corpus), now, result,
                grobid_alive=grobid_alive if grobid_alive is not None else (grobid_is_alive if extract_url is None else None))
            result.primed_from_human_reviews = _prime_from_human_reviews(
                client, cyclotron, plan, corpus_id, result.warnings)
            result.reviews = _send_reviews(client, cyclotron, plan, corpus_id, result.warnings)
            result.retired_labels = _retire_withdrawn_labels(client, cyclotron, plan, corpus_id, result.warnings)
            provenance = reproducibility_provenance(plan, cyclotron)
            if sample is not None:
                provenance = {**provenance, "sample": {key: sample[key] for key in (
                    "policy", "seed", "poolFingerprint", "selectionFingerprint") if key in sample}}
            auto_reject_gate = _auto_reject_gate(client, plan, corpus_id, now())
            predicted: list[tuple[dict[str, Any], dict[str, Any]]] = []
            for reference in pending:
                if decisions_allowed is not None and result.decided >= decisions_allowed:
                    result.stopped_because = "daily decision cap"
                    result.warnings.append(
                        f"{plan.definition.id} reached its cap of {plan.max_decisions_per_day} decisions today.")
                    break
                decision = asyncio.run(cyclotron.decide(model.prepare(reference_item(reference))))
                _reject_clear_miss(client, plan, auto_reject_gate, reference, decision.to_json(), now(), result)
                current = _decision_relations(client, reference["lineageId"])
                existing = current_relevance_decision(current, reference["lineageId"])
                if existing and json.loads(existing.get("metadata") or "{}").get("decisionId") == decision.decision_id:
                    continue
                records.extend(relevance_decision_records(
                    reference, decision.to_json(), cyclotron_id=plan.definition.id,
                    positive_label=plan.definition.classifiers[0].positive_label, now=now(), current_relations=current,
                    question=plan.definition.classifiers[0].question, labels=plan.definition.classifiers[0].labels,
                    review_control=plan.review_control, provenance=provenance))
                predicted.append((reference, decision.to_json()))
                result.decided += 1
            classifier = plan.definition.classifiers[0].id
            result.status = cyclotron.status(classifier).to_json()
            records.append(status_snapshot_record(plan.definition.id, result.status, now=now()))
            result.live_agreement = _live_agreement(client, plan, corpus_id, now(), result.stopped_because)
            records.append(shadow_agreement_record(plan.definition.id, result.live_agreement, now=now()))
            if plan.max_decisions_per_day is not None:
                already_decided_today = recorded_usage["decisions"] if recorded_usage and recorded_usage.get("day") == today else 0
                records.append(usage_record(plan.definition.id, day=today,
                                            decisions=already_decided_today + result.decided, now=now()))
            _apply(client, records)
            _record_original_predictions(client, plan, predicted, now())
            if snapshots and snapshot_uri:
                with tempfile.TemporaryDirectory() as scratch:
                    archive = Path(scratch) / SNAPSHOT_NAME
                    cyclotron.snapshot(archive)
                    snapshots.upload(archive, snapshot_uri)
        finally:
            cyclotron.close()
    finally:
        lease.release()
    return result


def _record_original_predictions(client, plan, predicted: list[tuple[dict[str, Any], dict[str, Any]]], decided_at: str) -> None:
    """Write each decided Reference's first prediction onto it (src/papyrus_content/reference_feed_keys.py); a Reference that has one keeps it."""
    from .reference_feed_keys import original_prediction_fields
    positive_label = plan.definition.classifiers[0].positive_label
    for reference, decision in predicted:
        (_, outcome), = decision["classifiers"].items()
        current = client.get_record("Reference", reference["id"])
        fields = original_prediction_fields(current, label=outcome["label"], positive_label=positive_label,
                                            confidence=outcome.get("confidence"), decided_at=decision.get("createdAt") or decided_at) if current else {}
        if fields:
            client.update_record("Reference", {"id": reference["id"], **fields})


def _sampled(client, pending: list[dict[str, Any]], corpus_id: str, size: int | None, seed: str | None,
             manifest: Mapping[str, Any] | None, include_housekeeping: bool):
    """The pending references a sample selects, in sample order, without those already decided.

    Returns the references and the sample record: the manifest plus what this
    run found (how many are still pending, already decided, or decided by an
    editor since the draw, which can no longer be a decision made before theirs).
    """
    if (size is None) == (manifest is None):
        raise ValueError("Give either a sample size with a seed, or a sample manifest, not both.")
    if manifest is None:
        if not seed:
            raise ValueError("A sample needs a seed so the draw can be reproduced.")
        manifest = draw_sample(pending, size=size, seed=seed, corpus_id=corpus_id, include_housekeeping=include_housekeeping)
    by_lineage = {reference["lineageId"]: reference for reference in pending}
    still_pending = [by_lineage[lineage] for lineage in manifest["lineageIds"] if lineage in by_lineage]
    undecided = [reference for reference in still_pending
                 if current_relevance_decision(_decision_relations(client, reference["lineageId"]),
                                               reference["lineageId"]) is None]
    record = {**manifest, "stillPending": len(still_pending), "alreadyDecided": len(still_pending) - len(undecided),
              "leftPending": len(manifest["lineageIds"]) - len(still_pending),
              "toDecide": [reference["lineageId"] for reference in undecided],
              "distribution": distribution(undecided, corpus_id)}
    return undecided, record


def _auto_reject_gate(client, plan: RelevanceCyclotronPlan, corpus_id: str, now: str) -> dict[str, Any]:
    classifier = plan.definition.classifiers[0]
    return auto_decision_gate(load_approved_proof(plan.approved_proof_path),
                              human_label_count=_human_label_count(client, classifier.labels, corpus_id), now=now)


def _clear_miss_of_decision(plan: RelevanceCyclotronPlan, gate: Mapping[str, Any], decision: Mapping[str, Any]) -> float | None:
    classifier = plan.definition.classifiers[0]
    result = decision["classifiers"][classifier.id]
    return clear_miss_probability(plan.auto_reject, gate, label=result["label"],
                                  probabilities=result.get("probabilities") or {}, labels=classifier.labels,
                                  positive_label=classifier.positive_label)


def _reject_clear_miss(client, plan: RelevanceCyclotronPlan, gate: Mapping[str, Any], reference: Mapping[str, Any],
                       decision: Mapping[str, Any], now: str, result: SweepResult) -> None:
    """Reject a pending reference the cyclotron is clearly sure is a miss, within the sweep cap. Never accepts."""
    if len(result.auto_rejected) >= plan.auto_reject["maxRejectsPerSweep"]:
        return
    probability = _clear_miss_of_decision(plan, gate, decision)
    if probability is None or latest_vote(reference) is not None:
        return
    if reject_reference_automatically(client, reference, cyclotron_id=plan.definition.id, probability=probability,
                                      proof_id=gate["proofId"], decision_id=decision["decisionId"], now=now):
        result.auto_rejected.append({"lineageId": reference["lineageId"], "probability": probability,
                                     "proofId": gate["proofId"]})


def _auto_rejections_a_sweep_would_make(client, plan: RelevanceCyclotronPlan, corpus_id: str,
                                        pending: Sequence[Mapping[str, Any]], now: str) -> list[dict[str, Any]]:
    if not plan.enabled or not plan.auto_reject["enabled"]:
        return []
    gate = _auto_reject_gate(client, plan, corpus_id, now)
    if not gate["allowed"]:
        return []
    classifier = plan.definition.classifiers[0]
    would_reject = []
    for reference in pending:
        if len(would_reject) >= plan.auto_reject["maxRejectsPerSweep"]:
            break
        relation = current_relevance_decision(_decision_relations(client, reference["lineageId"]), reference["lineageId"])
        if relation is None:
            continue
        recorded = json.loads(relation.get("metadata") or "{}")
        probability = clear_miss_probability(plan.auto_reject, gate, label=recorded.get("label"),
                                             probabilities=recorded.get("probabilities") or {},
                                             labels=classifier.labels, positive_label=classifier.positive_label)
        if probability is not None and latest_vote(reference) is None:
            would_reject.append({"lineageId": reference["lineageId"], "probability": probability,
                                 "proofId": gate["proofId"]})
    return would_reject


def _apply_review_rate_request(client, cyclotron, plan: RelevanceCyclotronPlan, warnings: list[str]) -> None:
    """Apply an editor's newest review-rate request once: a manual rate with an expiry, or clearing it.

    The request is a KnowledgeRawPayload the Newsroom writes; the cyclotron
    records who set the rate and when, and the status snapshot reports it.
    """
    record = client.get_record("KnowledgeRawPayload", review_rate_request_id(plan.definition.id))
    request = _latest_payload(client, record) if record else None
    if not request:
        return
    requested_at = _instant(request.get("requestedAt"))
    set_by = str(request.get("setBy") or "newsroom editor")
    override = cyclotron.status(plan.definition.classifiers[0].id).review_rate.override
    try:
        if request.get("clear"):
            if override is not None and _instant(override.set_at) < requested_at:
                cyclotron.clear_review_rate(set_by=set_by)
            return
        if override is not None and _instant(override.set_at) >= requested_at:
            return  # already applied
        expires_at = datetime.fromisoformat(request["expiresAt"].replace("Z", "+00:00")) if request.get("expiresAt") else None
        cyclotron.set_review_rate(float(request["rate"]), set_by=set_by, expires_at=expires_at)
    except (KeyError, TypeError, ValueError) as error:
        warnings.append(f"review-rate request not applied: {error}")


def _apply_priming_requests(client, cyclotron, plan: RelevanceCyclotronPlan, extract_url: ExtractUrl,
                            now: Callable[[], str], result: SweepResult,
                            grobid_alive: Callable[[], bool] | None = None) -> list[dict[str, Any]]:
    """Prime the running cyclotron with each editor request that has no outcome yet.

    A request is a KnowledgeRawPayload the Newsroom writes. Its outcome is a
    ``priming_outcome`` attachment on the same payload: applied (with the
    version the examples created) or failed (with a reason an editor can read).
    A failed request never stops the sweep. A source that cannot be read because
    an extraction service is down is not failed: it stays without an outcome and
    is tried again next sweep, up to ``MAX_TRANSIENT_ATTEMPTS`` tries. When the
    GROBID liveness preflight fails, no request is extracted this sweep. Returns the outcome records, which
    the sweep writes with its other records.
    """
    from decision_flywheel import Item, LabeledItem

    classifier = plan.definition.classifiers[0]
    requests = []
    for record in client.list_by_index("knowledgeRawPayloadsByOwner", safe_id(plan.definition.id)):
        if record.get("payloadKind") != PRIMING_REQUEST_KIND:
            continue
        request = _latest_payload(client, record)
        if not isinstance(request, dict):
            if request is not None:
                result.warnings.append(f"priming request {record['id']} is not a JSON object and was skipped")
            continue
        if _latest_payload(client, record, PRIMING_OUTCOME_ROLE) is None:
            requests.append((str(request.get("requestedAt") or ""), record["id"], record, request))
    outcomes = []
    if requests and grobid_alive is not None and not grobid_alive():
        result.warnings.append(f"GROBID is not responding; {len(requests)} priming request(s) left pending for the next sweep")
        return outcomes
    for _, _, record, request in sorted(requests, key=lambda entry: entry[:2]):
        outcome = {"requestId": request.get("requestId"), "url": request.get("url"), "label": request.get("label"),
                   "at": now()}
        try:
            url = normalize_priming_url(request.get("url"))
            label = priming_label(request, classifier.labels)
            try:
                values = dict(extract_url(url))
            except Exception as error:
                if getattr(error, "transient", False):
                    raise
                outcome.update(detail=str(error), code=getattr(error, "code", None))
                raise ValueError(UNREADABLE_MESSAGE.format(url=url)) from error
            explanation = str(request.get("explanation") or "").strip()
            example = LabeledItem(Item(priming_item_id(url), values), label, "trusted",
                                  {"human_feedback": explanation} if explanation else {})
            added = asyncio.run(cyclotron.add_priming_examples(
                {classifier.id: [example]}, added_by=str(request.get("requestedBy") or "newsroom editor")))
            outcome.update(state="applied", version=added["versions"][classifier.id], itemId=example.item.id)
            result.primed += 1
        except Exception as error:
            if getattr(error, "transient", False):
                previous = _latest_payload(client, record, PRIMING_ATTEMPTS_ROLE) or {}
                attempts = int(previous.get("attempts") or 0) + 1
                code, detail = getattr(error, "code", None), str(error)
                if attempts < MAX_TRANSIENT_ATTEMPTS:
                    result.priming_retrying += 1
                    result.warnings.append(f"priming request {request.get('requestId')} will be retried "
                                           f"(attempt {attempts} of {MAX_TRANSIENT_ATTEMPTS}): {detail}")
                    outcomes.append(priming_attempts_record(
                        record["id"], {"attempts": attempts, "lastCode": code, "lastError": detail, "at": outcome["at"]},
                        now=outcome["at"]))
                    continue
                outcome.update(state="failed", message=TRANSIENT_GIVE_UP_MESSAGE, code=code, detail=detail, attempts=attempts)
            else:
                outcome.update(state="failed", message=readable_engine_refusal(error))
            result.priming_failed += 1
            result.warnings.append(f"priming request {request.get('requestId')} failed: {outcome['message']}")
        outcomes.append(priming_outcome_record(record["id"], outcome, now=outcome["at"]))
    return outcomes


def _instant(value) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _latest_payload(client, record: Mapping[str, Any], role: str = "raw_payload") -> dict[str, Any] | None:
    attachments = [attachment for attachment in client.list_by_index("modelAttachmentsByOwnerRoleAndSortKey", record["id"])
                   if attachment.get("role") == role and attachment.get("status") != "deleted"]
    attachments.sort(key=lambda attachment: str(attachment.get("updatedAt") or attachment.get("createdAt") or ""))
    for attachment in reversed(attachments):
        payload = parse_jsonish((download_attachment_buffer(client, attachment) or b"").decode("utf-8", "replace"))
        if isinstance(payload, dict):
            return payload
    return None


def _recorded_usage(client, cyclotron_id: str) -> dict[str, Any] | None:
    for record in client.list_by_index("knowledgeRawPayloadsByOwner", safe_id(cyclotron_id)):
        if record.get("payloadKind") == USAGE_PAYLOAD_KIND:
            return _latest_payload(client, record)
    return None


def _live_agreement(client, plan: RelevanceCyclotronPlan, corpus_id: str, now: str,
                    stopped_because: str | None = None) -> dict[str, Any]:
    """Agreement of the cyclotron's earlier suggestions with what people then decided."""
    classifier = plan.definition.classifiers[0]
    comparisons = []
    for status in REVIEWED_STATUSES:
        for reference in _current(client.list_by_index("referencesByCurationStatusKey", f"{corpus_id}#{status}")):
            decision_relation = current_relevance_decision(_decision_relations(client, reference["lineageId"]),
                                                           reference["lineageId"])
            if decision_relation is None:
                continue
            comparison = comparison_of_suggestion_with_human_decision(
                reference, decision_relation, labels=classifier.labels)
            if comparison is not None:
                comparisons.append(comparison)
    return {**live_agreement(comparisons, positive_label=classifier.positive_label, now=now),
            "autoDecision": auto_decision_gate(load_approved_proof(plan.approved_proof_path),
                                               human_label_count=_human_label_count(client, classifier.labels, corpus_id),
                                               now=now),
            "loop": {"enabled": plan.enabled, "stoppedBecause": stopped_because, "lastSweepAt": now,
                     "maxDecisionsPerDay": plan.max_decisions_per_day}}


def _human_label_count(client, labels: Sequence[str], corpus_id: str) -> int:
    count = 0
    for status in REVIEWED_STATUSES:
        for reference in _current(client.list_by_index("referencesByCurationStatusKey", f"{corpus_id}#{status}")):
            if human_label_for_review(reference, labels=labels) is not None:
                count += 1
    return count


def _prime_from_human_reviews(client, cyclotron, plan: RelevanceCyclotronPlan, corpus_id: str,
                              warnings: list[str]) -> int:
    """Teach the cyclotron from every explicit human review of a Reference it has not decided itself.

    A decided Reference already teaches through its review. A Reference no one
    decided (imported, or reviewed before the cyclotron existed) can only teach
    as a priming example, and only when a person explicitly accepted or rejected
    it. The editor's note travels as human feedback, never inside the item.
    Idempotent: examples the store already holds change nothing.
    """
    from decision_flywheel import Item, LabeledItem

    classifier = plan.definition.classifiers[0]
    added = 0
    for status in REVIEWED_STATUSES:
        for reference in _current(client.list_by_index("referencesByCurationStatusKey", f"{corpus_id}#{status}")):
            if current_relevance_decision(_decision_relations(client, reference["lineageId"]),
                                          reference["lineageId"]) is not None:
                continue
            label = human_label_for_review(reference, labels=classifier.labels)
            if label is None:
                continue
            note = str(reference.get("curationStatusReason") or "").strip()
            item = reference_item({**reference, "curationStatusReason": None})
            example = LabeledItem(Item(item.id, item.values), label, "trusted",
                                  {"human_feedback": note} if note else {})
            try:
                asyncio.run(cyclotron.add_priming_examples(
                    {classifier.id: [example]}, added_by=str(latest_vote(reference)["authorLabel"] or "newsroom editor")))
            except ValueError as error:
                warnings.append(f"{reference['lineageId']}: {error}")
                continue
            added += 1
    return added


def _retire_withdrawn_labels(client, cyclotron, plan: RelevanceCyclotronPlan, corpus_id: str,
                             warnings: list[str]) -> int:
    """Retract the cyclotron's label for a decided reference whose latest curation no longer gives a human label.

    A person who sets a reviewed reference back to pending, or a later curation
    by anyone else that is not an explicit human label, withdraws the label the
    cyclotron learned from. The cyclotron's history keeps the retraction.
    """
    labels = plan.definition.classifiers[0].labels
    retired = 0
    for status in ("pending", *REVIEWED_STATUSES):
        for reference in _current(client.list_by_index("referencesByCurationStatusKey", f"{corpus_id}#{status}")):
            decision_relation = current_relevance_decision(_decision_relations(client, reference["lineageId"]),
                                                           reference["lineageId"])
            vote = latest_vote(reference)
            if vote is None or human_label_for_review(reference, labels=labels) is not None:
                continue
            if decision_relation is None:
                retired += _retract_priming_example(cyclotron, plan, reference, warnings)
                continue
            decision_id = json.loads(decision_relation.get("metadata") or "{}").get("decisionId")
            if not decision_id:
                continue
            try:
                asyncio.run(cyclotron.undo_review(decision_id, review_id=f"retire:{vote['id']}"))
            except ValueError as error:
                if "no label to undo" not in str(error):
                    warnings.append(f"{reference['lineageId']}: {error}")
                continue
            retired += 1
    return retired


def _retract_priming_example(cyclotron, plan: RelevanceCyclotronPlan, reference: Mapping[str, Any],
                             warnings: list[str]) -> int:
    classifier_id = plan.definition.classifiers[0].id
    try:
        outcome = asyncio.run(cyclotron.retract_priming_examples(
            {classifier_id: [reference_item(reference).id]}, retracted_by="papyrus: human review withdrawn"))
    except ValueError as error:
        warnings.append(f"{reference['lineageId']}: {error}")
        return 0
    return len(outcome["retracted"].get(classifier_id, ()))


def _send_reviews(client, cyclotron, plan: RelevanceCyclotronPlan, corpus_id: str, warnings: list[str]) -> int:
    """Send each decided, reviewed reference's latest vote to the cyclotron. Idempotent by vote id."""
    labels = plan.definition.classifiers[0].labels
    sent = 0
    for status in REVIEWED_STATUSES:
        for reference in _current(client.list_by_index("referencesByCurationStatusKey", f"{corpus_id}#{status}")):
            decision_relation = current_relevance_decision(_decision_relations(client, reference["lineageId"]),
                                                           reference["lineageId"])
            if decision_relation is None:
                continue
            decision_id = json.loads(decision_relation.get("metadata") or "{}").get("decisionId")
            latest = latest_vote(reference)
            if latest is None or not decision_id:
                continue
            if not curation_was_made_by_a_human(reference):
                continue
            label = relevance_label_for_review(reference, labels=labels)
            try:
                asyncio.run(cyclotron.review(
                    decision_id, label, explanation=reference.get("curationStatusReason"),
                    reason_code=latest["reasonCode"], reviewer=latest["authorLabel"],
                    review_id=latest["id"]))
            except ValueError as error:
                # For example a review without a label after a labeled one: the
                # editor's history stays in Papyrus; the cyclotron keeps its label.
                warnings.append(f"{reference['lineageId']}: {error}")
                continue
            sent += 1
    return sent


def _decision_relations(client, lineage_id: str) -> list[dict[str, Any]]:
    return [relation for relation in client.list_by_index("semanticRelationsBySubjectState", f"reference#{lineage_id}#current")
            if relation.get("predicate") == RELEVANCE_RELATION]


def _current(references) -> list[dict[str, Any]]:
    return [reference for reference in references if reference.get("versionState") == "current"
            and normalize_reference_curation_status(reference.get("curationStatus")) is not None]


def _apply(client, records) -> None:
    changes = []
    for record in expand_private_payload_records(records):
        current = client.get_record(record["modelName"], record["expected"]["id"])
        change = build_record_change_from_current(record["modelName"], record["expected"], current)
        if "attachmentBody" in record:
            change["attachmentBody"] = record["attachmentBody"]
        changes.append(change)
    apply_record_changes(client, changes)


def references_decide_relevance(flags: list[str]) -> None:
    """papyrus references decide-relevance [--config <steering.yml>] [--doctrine <doctrine.yml>]
    [--max-count N] [--worker <name>] [--apply] [--json]
    [--sample N --seed S [--sample-include-housekeeping] | --sample-list <manifest.json>]
    [--sample-manifest <path>]

    Dry run by default: lists the pending references a sweep would decide and
    makes no model call and no write. ``--apply`` runs the sweep.

    ``--sample N --seed S`` decides a deterministic spread sample instead of the
    oldest pending references; ``--sample-manifest`` writes the draw to a local
    file, and ``--sample-list`` decides from such a file so every batch stays on
    the same references. Pending references with a current decision are skipped.
    """
    import os
    import socket

    from .graphql_authoring import create_authoring_client
    from .newsroom_doctrine import describe_doctrine_choice, load_publication_doctrine_seed, require_explicit_doctrine
    from .options import parse_options
    from .steering import require_steering_config

    options = parse_options(flags)
    if options.get("apply"):
        require_explicit_doctrine(options, "references decide-relevance --apply")
    steering_config = require_steering_config(options.get("config"))
    if not steering_config.get("relevanceCyclotron"):
        raise ValueError("This publication's steering config has no relevanceCyclotron block; see docs/cyclotron-priming.md.")
    doctrine_file = options.get("doctrine") if isinstance(options.get("doctrine"), str) else None
    doctrine_choice = describe_doctrine_choice(doctrine_file)
    doctrine = load_publication_doctrine_seed(doctrine_file)["doctrine"]
    max_count = int(options["max-count"]) if options.get("max-count") not in (None, True) else None
    worker = options.get("worker") if isinstance(options.get("worker"), str) else f"{socket.gethostname()}:{os.getpid()}"
    for flag in ("sample", "seed", "sample-list", "sample-manifest"):
        if options.get(flag) is True:
            raise ValueError(f"--{flag} needs a value.")
    sample_size = int(options["sample"]) if options.get("sample") else None
    if options.get("sample-list") and sample_size is not None:
        raise ValueError("Use either --sample N --seed S or --sample-list <manifest>, not both.")
    if sample_size is not None and not options.get("seed"):
        raise ValueError("--sample needs --seed so the draw is reproducible.")
    corpus_id = knowledge_corpus_id(require_corpus_config(
        dict(steering_config), relevance_corpus_key(steering_config), "relevanceCyclotron.corpusKey"))
    manifest = load_manifest(options["sample-list"], corpus_id) if options.get("sample-list") else None
    client, _ = create_authoring_client()
    result = run_decide_relevance(client, steering_config, doctrine, apply=bool(options.get("apply")),
                                  worker=worker, max_count=max_count, sample_size=sample_size,
                                  sample_seed=options.get("seed"), sample_manifest=manifest,
                                  include_housekeeping=bool(options.get("sample-include-housekeeping")))
    if options.get("sample-manifest") and result.sample is not None:
        run_only = ("stillPending", "alreadyDecided", "leftPending", "toDecide", "distribution")
        write_manifest({key: value for key, value in result.sample.items() if key not in run_only},
                       options["sample-manifest"])
    if options.get("json"):
        print(json.dumps({**result.to_json(), "doctrine": doctrine_choice}, indent=2, sort_keys=True))
        return
    action = "apply" if result.applied else "dry-run"
    kind = "default" if doctrine_choice["isDefault"] else "explicit"
    print(f"references\tdecide-relevance\tdoctrine\t{kind}\t{doctrine_choice['path']}\t{doctrine_choice['firstMissionLine']}")
    print(f"references\tdecide-relevance\t{action}\tpending\t{len(result.pending)}")
    if result.sample is not None:
        sample = result.sample
        print(f"references\tdecide-relevance\tsample\t{sample['policy']}\tseed\t{sample['seed']}\tdrawn\t{sample['size']}"
              f"\tpool\t{sample['poolSize']}\talready-decided\t{sample['alreadyDecided']}\tno-longer-pending\t{sample['leftPending']}")
        for origin, counts in sample["strata"].items():
            print(f"references\tdecide-relevance\tsample-origin\t{origin}\tpool\t{counts['pool']}\tsampled\t{counts['sampled']}")
        for month, count in sample["distribution"]["byImportedMonth"].items():
            print(f"references\tdecide-relevance\tsample-imported-month\t{month}\t{count}")
    if result.applied:
        print(f"references\tdecide-relevance\tdecided\t{result.decided}")
        print(f"references\tdecide-relevance\treviews-sent\t{result.reviews}")
        print(f"references\tdecide-relevance\tprimed\t{result.primed}\tfailed\t{result.priming_failed}")
        rate = (result.status or {}).get("reviewRate") or {}
        print(f"references\tdecide-relevance\treview-rate\t{rate.get('state')}\t{rate.get('rate')}")
    verb = "auto-rejected" if result.applied else "would-auto-reject"
    for rejection in result.auto_rejected:
        print(f"references\tdecide-relevance\t{verb}\t{rejection['lineageId']}\t{rejection['probability']}\t{rejection['proofId']}")
    for warning in result.warnings:
        print(f"references\tdecide-relevance\twarning\t{warning}")
