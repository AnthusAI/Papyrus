"""The decide-relevance sweep: the candidate pipeline's hook into the cyclotron.

One sweep, run by a worker after research intake and on a schedule:

1. Claims the publication's ``cyclotron.relevance`` Assignment (one writer).
2. Restores the cyclotron store from the private media bucket when this worker
   has no local copy.
3. Sends editors' reviews of decided references back to the cyclotron, using
   the existing ``reference_curation`` Messages and scope-training rule.
4. Decides every current pending ``Reference`` of the canonical corpus and
   records each new decision as a ``relevance_decision_is`` relation.
5. Records the ``cyclotron-status/v1`` snapshot, saves the store to the
   private bucket, and releases the claim.

It never changes a Reference's curation status. Nothing runs between sweeps:
the worker, the store and the bucket all scale to zero.
"""
from __future__ import annotations

import asyncio
import json
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from .assignments import active_claim_held_by_different_assignee, apply_assignment_action
from .ids import knowledge_corpus_id, safe_id
from .model_attachments import download_attachment_buffer, expand_private_payload_records, parse_jsonish
from .records import apply_record_changes, build_record_change_from_current
from .reference_policy import normalize_reference_curation_status
from .relevance_cyclotron import (RelevanceCyclotronPlan, build_relevance_cyclotron, decision_model_from_environment,
                                  optimizer_from_environment)
from .relevance_decisions import (RELEVANCE_RELATION, current_relevance_decision, relevance_decision_records,
                                  relevance_label_for_review, status_snapshot_record)
from .steering import require_corpus_config

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
    reviews: int = 0
    status: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {"applied": self.applied, "pendingReferences": self.pending, "decided": self.decided,
                "reviewsSent": self.reviews, "status": self.status, "warnings": self.warnings}


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


def reference_item(reference: Mapping[str, Any]):
    """The cyclotron item for a candidate reference: what an editor sees when deciding."""
    from decision_flywheel import Item

    source = reference.get("sourceUri") or ""
    domain = source.split("//", 1)[-1].split("/", 1)[0] if "//" in source else ""
    lines = [reference.get("title") or reference.get("externalItemId") or reference["lineageId"]]
    if domain:
        lines.append(f"Source: {domain}")
    if reference.get("sourcePublishedAt"):
        lines.append(f"Published: {str(reference['sourcePublishedAt'])[:10]}")
    if reference.get("curationStatusReason"):
        lines.append(f"Why it was proposed: {reference['curationStatusReason']}")
    values = {"text": "\n".join(str(line) for line in lines), "title": reference.get("title"),
              "source_uri": source or None, "domain": domain or None,
              "published_at": reference.get("sourcePublishedAt"),
              "ingestion_rationale": reference.get("curationStatusReason")}
    return Item(reference.get("lineageId") or reference["id"], {key: value for key, value in values.items() if value})


def run_decide_relevance(client, steering_config: Mapping[str, Any], doctrine, *, apply: bool, worker: str,
                         max_count: int | None = None, model=None, optimizer=None, snapshots=None,
                         now: Callable[[], str] | None = None) -> SweepResult:
    """Run one sweep. ``model``, ``optimizer`` and ``snapshots`` default to the configured providers."""
    now = now or (lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    plan = build_relevance_cyclotron(steering_config, doctrine)
    corpus = require_corpus_config(dict(steering_config), steering_config["canonicalTopicSet"]["corpusKey"],
                                   "canonicalTopicSet.corpusKey")
    corpus_id = knowledge_corpus_id(corpus)
    pending = _current(client.list_by_index("referencesByCurationStatusKey", f"{corpus_id}#pending"))
    pending.sort(key=lambda reference: str(reference.get("importedAt") or reference.get("createdAt") or ""))
    if max_count is not None:
        pending = pending[:max_count]
    result = SweepResult(applied=apply, pending=[reference["lineageId"] for reference in pending])
    if not apply:
        return result

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
        model = model if model is not None else decision_model_from_environment(plan)
        optimizer = optimizer if optimizer is not None else optimizer_from_environment(plan)
        cyclotron = Cyclotron.open(local, plan.definition, model, optimizer, lease=_HeldLease(),
                                   max_requests=plan.max_requests, review_program=plan.review_program,
                                   seed_rubrics=plan.seed_rubrics)
        try:
            result.reviews = _send_reviews(client, cyclotron, plan, corpus_id, result.warnings)
            records = []
            for reference in pending:
                decision = asyncio.run(cyclotron.decide(reference_item(reference)))
                current = _decision_relations(client, reference["lineageId"])
                existing = current_relevance_decision(current, reference["lineageId"])
                if existing and json.loads(existing.get("metadata") or "{}").get("decisionId") == decision.decision_id:
                    continue
                records.extend(relevance_decision_records(
                    reference, decision.to_json(), cyclotron_id=plan.definition.id,
                    positive_label=plan.definition.classifiers[0].positive_label, now=now(), current_relations=current,
                    question=plan.definition.classifiers[0].question, labels=plan.definition.classifiers[0].labels,
                    review_control=plan.review_control))
                result.decided += 1
            classifier = plan.definition.classifiers[0].id
            result.status = cyclotron.status(classifier).to_json()
            records.append(status_snapshot_record(plan.definition.id, result.status, now=now()))
            _apply(client, records)
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


def _send_reviews(client, cyclotron, plan: RelevanceCyclotronPlan, corpus_id: str, warnings: list[str]) -> int:
    """Send each decided, reviewed reference's curation to the cyclotron. Idempotent by message id."""
    labels = plan.definition.classifiers[0].labels
    sent = 0
    for status in REVIEWED_STATUSES:
        for reference in _current(client.list_by_index("referencesByCurationStatusKey", f"{corpus_id}#{status}")):
            decision_relation = current_relevance_decision(_decision_relations(client, reference["lineageId"]),
                                                           reference["lineageId"])
            if decision_relation is None:
                continue
            decision_id = json.loads(decision_relation.get("metadata") or "{}").get("decisionId")
            messages = _curation_messages(client, reference["lineageId"])
            if not messages or not decision_id:
                continue
            latest = messages[-1]
            metadata = latest.get("metadata") or {}
            label = relevance_label_for_review(reference, messages, labels=labels)
            try:
                asyncio.run(cyclotron.review(
                    decision_id, label, explanation=reference.get("curationStatusReason"),
                    reason_code=metadata.get("reasonCode"), reviewer=latest.get("authorLabel"),
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


def _curation_messages(client, lineage_id: str) -> list[dict[str, Any]]:
    """The reference's curation Messages with their metadata, oldest first."""
    messages = []
    for relation in client.list_by_index("semanticRelationsByObjectState", f"reference#{lineage_id}#current"):
        if relation.get("predicate") != "comment" or relation.get("subjectKind") != "message":
            continue
        if relation.get("relationState") != "current":
            continue
        message = client.get_record("Message", relation["subjectId"])
        if not message or message.get("messageKind") != "reference_curation":
            continue
        messages.append({**message, "metadata": _owner_metadata(client, message)})
    messages.sort(key=lambda message: str(message.get("createdAt") or ""))
    return messages


def _owner_metadata(client, record: Mapping[str, Any]) -> dict[str, Any]:
    metadata = parse_jsonish(record.get("metadata"))
    if isinstance(metadata, dict) and metadata:
        return metadata
    for attachment in client.list_by_index("modelAttachmentsByOwnerRoleAndSortKey", record["id"]):
        if attachment.get("role") == "metadata":
            payload = parse_jsonish((download_attachment_buffer(client, attachment) or b"").decode("utf-8", "replace"))
            if isinstance(payload, dict):
                return payload
    return {}


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

    Dry run by default: lists the pending references a sweep would decide and
    makes no model call. ``--apply`` runs the sweep.
    """
    import os
    import socket

    from .graphql_authoring import create_authoring_client
    from .newsroom_doctrine import load_publication_doctrine_seed
    from .options import parse_options
    from .steering import require_steering_config

    options = parse_options(flags)
    steering_config = require_steering_config(options.get("config"))
    if not steering_config.get("relevanceCyclotron"):
        raise ValueError("This publication's steering config has no relevanceCyclotron block; see docs/relevance-cyclotron.md.")
    doctrine = load_publication_doctrine_seed(options.get("doctrine"))["doctrine"]
    max_count = int(options["max-count"]) if options.get("max-count") not in (None, True) else None
    worker = options.get("worker") if isinstance(options.get("worker"), str) else f"{socket.gethostname()}:{os.getpid()}"
    client, _ = create_authoring_client()
    result = run_decide_relevance(client, steering_config, doctrine, apply=bool(options.get("apply")),
                                  worker=worker, max_count=max_count)
    if options.get("json"):
        print(json.dumps(result.to_json(), indent=2, sort_keys=True))
        return
    action = "apply" if result.applied else "dry-run"
    print(f"references\tdecide-relevance\t{action}\tpending\t{len(result.pending)}")
    if result.applied:
        print(f"references\tdecide-relevance\tdecided\t{result.decided}")
        print(f"references\tdecide-relevance\treviews-sent\t{result.reviews}")
        rate = (result.status or {}).get("reviewRate") or {}
        print(f"references\tdecide-relevance\treview-rate\t{rate.get('state')}\t{rate.get('rate')}")
    for warning in result.warnings:
        print(f"references\tdecide-relevance\twarning\t{warning}")
