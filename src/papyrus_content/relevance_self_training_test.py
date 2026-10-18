"""Human-only self-training, shadow agreement, the cost cap and the off switch, on a scripted model."""
import json
from pathlib import Path
from unittest import mock

import pytest

from features_backend.steps.cyclotron_relevance_sweep_steps import (CORPUS_ID, DOCTRINE, LocalBucket, Model,
                                                                     SweepClient, configure, reference)
from papyrus_content.relevance_decisions import current_relevance_decision
from papyrus_content.relevance_sweep import _current, run_decide_relevance


def prepared_context(tmp_path, *, pending=3, relevance_overrides=None):
    context = type("Context", (), {})()
    context.tmp = str(tmp_path)
    configure(context, tmp_path / "worker")
    if relevance_overrides:
        context.steering["relevanceCyclotron"].update(relevance_overrides)
    return context


def curate(client, item, *, status, actor_kind, reason=None, note=None, at="2026-10-09T12:00:00Z"):
    client.tables["Reference"][item["id"]].update({
        "curationStatus": status, "curationStatusKey": f"{CORPUS_ID}#{status}", "curationStatusReason": note})
    message_id = f"message-reference-curation-{item['lineageId']}-{status}"
    metadata = {"reasonCode": reason, **({"actorKind": actor_kind} if actor_kind else {})}
    client.upsert("Message", {"id": message_id, "messageKind": "reference_curation", "authorLabel": "someone",
                              "createdAt": at, "metadata": json.dumps(metadata)})
    client.upsert("SemanticRelation", {
        "id": f"relation-{message_id}", "relationState": "current", "predicate": "comment", "subjectKind": "message",
        "subjectId": message_id, "objectKind": "reference", "objectLineageId": item["lineageId"],
        "objectStateKey": f"reference#{item['lineageId']}#current", "subjectStateKey": f"message#{message_id}#current"})


class TrainingRecordingModel(Model):
    def __init__(self):
        super().__init__()
        self.training_label_counts = []

    async def classify_many(self, configs, target, training, **kwargs):
        self.training_label_counts.append(sum(len(rows) for rows in training.values()))
        return await super().classify_many(configs, target, training, **kwargs)


def sweep(context, model, client, tmp_path, *, now="2026-10-18T10:00:00Z"):
    stored_bodies = client.bodies

    def store_body(recording_client, attachment, body):
        recording_client.upsert("ModelAttachment", attachment)
        stored_bodies[attachment["id"]] = body

    with mock.patch("papyrus_content.relevance_sweep.knowledge_corpus_id", return_value=CORPUS_ID), \
            mock.patch("papyrus_content.records.upload_attachment_body", side_effect=store_body), \
            mock.patch("papyrus_content.assignments.upload_attachment_body", side_effect=store_body), \
            mock.patch("papyrus_content.relevance_sweep.download_attachment_buffer",
                       side_effect=lambda recording_client, attachment: stored_bodies.get(attachment["id"])):
        return run_decide_relevance(client, context.steering, DOCTRINE, apply=True, worker="worker-a", model=model,
                                    snapshots=LocalBucket(tmp_path / "bucket"), now=lambda: now)


def labels_in_store(context):
    from decision_flywheel import Cyclotron
    from papyrus_content.relevance_cyclotron import build_relevance_cyclotron

    plan = build_relevance_cyclotron(context.steering, DOCTRINE)
    with Cyclotron.open(plan.local_path, plan.definition, Model(), review_program=plan.review_program) as cyclotron:
        return {row["item"].id: row["label"] for row in cyclotron.labels()}


def two_pending_references():
    return [reference("reference-a", "A security advisory for model servers", "pending"),
            reference("reference-bb", "A vendor launch announcement", "pending")]


def test_only_a_human_curation_teaches_the_cyclotron(tmp_path):
    context = prepared_context(tmp_path)
    first, second = two_pending_references()
    client = SweepClient({"Reference": [first, second]})
    sweep(context, Model(), client, tmp_path)
    curate(client, first, status="accepted", actor_kind="service")
    curate(client, second, status="rejected", actor_kind="human", reason="out_of_scope")
    sweep(context, Model(), client, tmp_path)
    assert labels_in_store(context) == {"reference-bb": "exclude"}


def test_a_curation_with_no_recorded_actor_never_teaches(tmp_path):
    context = prepared_context(tmp_path)
    first, second = two_pending_references()
    client = SweepClient({"Reference": [first, second]})
    sweep(context, Model(), client, tmp_path)
    curate(client, first, status="accepted", actor_kind=None)
    sweep(context, Model(), client, tmp_path)
    assert labels_in_store(context) == {}


def test_a_human_review_of_a_reference_nobody_decided_primes_the_cyclotron_and_an_agent_one_does_not(tmp_path):
    context = prepared_context(tmp_path)
    human_reviewed = reference("reference-human", "A human accepted security paper", "pending")
    agent_reviewed = reference("reference-agent", "An agent accepted security paper", "pending")
    client = SweepClient({"Reference": [human_reviewed, agent_reviewed]})
    curate(client, human_reviewed, status="accepted", actor_kind="human", note="Core topic.")
    curate(client, agent_reviewed, status="accepted", actor_kind="service")
    result = sweep(context, Model(), client, tmp_path)
    assert result.primed_from_human_reviews == 1
    again = sweep(context, Model(), client, tmp_path)
    assert again.primed_from_human_reviews == 1 and again.warnings == []


def test_a_human_label_on_a_decided_reference_reaches_the_next_decision_prompt(tmp_path):
    context = prepared_context(tmp_path)
    decided, later = two_pending_references()
    client = SweepClient({"Reference": [decided]})
    first_model = TrainingRecordingModel()
    sweep(context, first_model, client, tmp_path)
    assert first_model.training_label_counts == [0]
    curate(client, decided, status="rejected", actor_kind="human", reason="out_of_scope", at="2999-01-01T00:00:00Z")
    client.upsert("Reference", later)
    second_model = TrainingRecordingModel()
    sweep(context, second_model, client, tmp_path)
    assert second_model.training_label_counts == [1]


def test_live_agreement_counts_only_human_reviews_that_came_after_the_suggestion(tmp_path):
    context = prepared_context(tmp_path)
    first, second = two_pending_references()
    client = SweepClient({"Reference": [first, second]})
    sweep(context, Model(), client, tmp_path)
    curate(client, first, status="accepted", actor_kind="human", at="2999-01-01T00:00:00Z")
    curate(client, second, status="accepted", actor_kind="service", at="2999-01-01T00:00:00Z")
    result = sweep(context, Model(), client, tmp_path)
    assert result.live_agreement["comparisons"] == 1
    assert result.live_agreement["agreement"] == 1.0
    reviewed_before_the_suggestion = reference("reference-early", "A security note reviewed first", "pending")
    client.upsert("Reference", reviewed_before_the_suggestion)
    curate(client, reviewed_before_the_suggestion, status="accepted", actor_kind="human", at="2000-01-01T00:00:00Z")
    assert sweep(context, Model(), client, tmp_path).live_agreement["comparisons"] == 1


def test_a_suggestion_records_the_labels_and_doctrine_that_produced_it(tmp_path):
    context = prepared_context(tmp_path)
    first, second = two_pending_references()
    client = SweepClient({"Reference": [first, second]})
    sweep(context, Model(), client, tmp_path)
    metadata = json.loads(current_relevance_decision(client.list_by_index("semanticRelationsBySubjectState",
                          f"reference#{first['lineageId']}#current"), first["lineageId"])["metadata"])
    assert metadata["provenance"]["labelSet"] == ["include", "exclude"]
    assert len(metadata["provenance"]["doctrineFingerprint"]) == 16
    assert metadata["provenance"]["teachingLabels"] == 0


def test_a_switched_off_cyclotron_decides_nothing(tmp_path):
    context = prepared_context(tmp_path, relevance_overrides={"enabled": False})
    model = Model()
    client = SweepClient({"Reference": two_pending_references()})
    result = sweep(context, model, client, tmp_path)
    assert (model.calls, result.decided, result.stopped_because) == (0, 0, "disabled")


def test_the_daily_decision_cap_stops_the_sweep_and_resets_the_next_day(tmp_path):
    context = prepared_context(tmp_path, relevance_overrides={"maxDecisionsPerDay": 1})
    client = SweepClient({"Reference": two_pending_references()})
    first_run = sweep(context, Model(), client, tmp_path)
    assert (first_run.decided, first_run.stopped_because) == (1, "daily decision cap")
    same_day = sweep(context, Model(), client, tmp_path, now="2026-10-18T20:00:00Z")
    assert (same_day.decided, same_day.stopped_because) == (0, "daily decision cap")
    next_day = sweep(context, Model(), client, tmp_path, now="2026-10-19T01:00:00Z")
    assert next_day.decided == 1 and next_day.stopped_because is None
